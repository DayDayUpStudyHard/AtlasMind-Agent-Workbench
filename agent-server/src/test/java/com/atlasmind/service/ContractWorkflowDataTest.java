package com.atlasmind.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/** Exercises the real signal queries and derivation together, without external services. */
class ContractWorkflowDataTest {
    private JdbcTemplate jdbc;
    private ContractWorkflowService service;

    @BeforeEach
    void setUp() {
        jdbc = new JdbcTemplate(new DriverManagerDataSource(
                "jdbc:h2:mem:" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1", "sa", ""));
        service = new ContractWorkflowService(jdbc);
        jdbc.execute("CREATE TABLE contract_case(id BIGINT PRIMARY KEY, status VARCHAR(40), create_time TIMESTAMP, expiry_date DATE, deleted INT DEFAULT 0)");
        jdbc.execute("CREATE TABLE contract_document(id BIGINT PRIMARY KEY, case_id BIGINT, document_type VARCHAR(20), version INT, parse_status VARCHAR(20), parse_quality VARCHAR(20), create_time TIMESTAMP, deleted INT DEFAULT 0)");
        jdbc.execute("CREATE TABLE contract_extraction_snapshot(id BIGINT PRIMARY KEY, case_id BIGINT, document_id BIGINT, status VARCHAR(40))");
        jdbc.execute("CREATE TABLE contract_extracted_element(id BIGINT PRIMARY KEY, snapshot_id BIGINT, review_status VARCHAR(40))");
        jdbc.execute("CREATE TABLE agent_run(id BIGINT PRIMARY KEY, subject_id BIGINT, subject_type VARCHAR(40), run_type VARCHAR(40), status VARCHAR(40))");
        jdbc.execute("CREATE TABLE contract_analysis_workflow(id BIGINT PRIMARY KEY, case_id BIGINT, timeline_status VARCHAR(40))");
        jdbc.execute("CREATE TABLE contract_timeline_node(id BIGINT PRIMARY KEY, case_id BIGINT, source VARCHAR(40), manual_override INT DEFAULT 0, review_status VARCHAR(40))");
        jdbc.execute("CREATE TABLE contract_review_finding(id BIGINT PRIMARY KEY, case_id BIGINT, run_id BIGINT, status VARCHAR(40))");
        jdbc.update("INSERT INTO contract_case(id,status,create_time) VALUES(1,'READY_FOR_REVIEW','2026-10-20 09:00:00')");
        jdbc.update("INSERT INTO contract_document VALUES(10,1,'MAIN',1,'READY','HIGH','2026-10-20 09:15:00',0)");
    }

    @Test
    void detailAndListReadTheSameFailedTimelineSignal() {
        snapshot("CONFIRMED");
        jdbc.update("INSERT INTO contract_analysis_workflow VALUES(1,1,'FAILED')");
        jdbc.update("INSERT INTO contract_timeline_node VALUES(1,1,'AGENT_FINAL',0,'CONFIRMED')");
        assertThat(service.workflow(1L).get("blockedReason")).isEqualTo("TIMELINE_FAILED");
        assertThat(listRow().get("stage")).isEqualTo("TIMELINE_CONFIRM");
    }

    @Test
    void replacedDocumentDoesNotReuseOldConfirmedSnapshot() {
        snapshot("CONFIRMED");
        jdbc.update("INSERT INTO contract_document VALUES(11,1,'MAIN',2,'READY','HIGH',CURRENT_TIMESTAMP,0)");
        assertThat(service.workflow(1L).get("stage")).isEqualTo("ELEMENT_CONFIRM");
        assertThat(listRow().get("stage")).isEqualTo("ELEMENT_CONFIRM");
    }

    @Test
    void countsActualElementReviewsAndAdvancesAfterAllAreReviewed() {
        snapshot("READY_FOR_CONFIRMATION");
        jdbc.update("INSERT INTO contract_extracted_element VALUES(1,20,'CONFIRMED'),(2,20,NULL),(3,20,'NOT_APPLICABLE')");
        Map<String, Object> result = service.workflow(1L);
        assertThat(detail(result).get("counters")).isEqualTo(Map.of("total", 3, "confirmed", 2, "pending", 1));
        jdbc.update("UPDATE contract_extracted_element SET review_status='CONFIRMED' WHERE id=2");
        service.evict(1L);
        assertThat(service.workflow(1L).get("stage")).isEqualTo("TIMELINE_CONFIRM");
        assertThat(listRow().get("stage")).isEqualTo("TIMELINE_CONFIRM");
    }

    @Test
    void emptyUnconfirmedSnapshotDoesNotAutomaticallyComplete() {
        snapshot("READY_FOR_CONFIRMATION");
        assertThat(service.workflow(1L).get("stage")).isEqualTo("ELEMENT_CONFIRM");
    }

    @Test
    void activeParseKeepsUploadTimeAndMissingDocumentIsNotLimited() {
        jdbc.update("UPDATE contract_document SET parse_status='PARSING'");
        Map<String, Object> result = service.workflow(1L);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> stages = (List<Map<String, Object>>) result.get("stages");
        assertThat(stages.get(1).get("enteredAt")).isEqualTo("2026-10-20T09:15");
        jdbc.update("DELETE FROM contract_document WHERE id=10");
        service.evict(1L);
        assertThat(service.workflow(1L).get("limited")).isEqualTo(false);
    }

    @Test
    void laterBusinessStatusesAdvanceLegacyCasesWithoutOldExtractionData() {
        Map<String, String> expected = Map.of("APPROVED", "SIGNING", "READY_TO_SIGN", "SIGNING",
                "SIGNED", "FULFILLMENT", "IN_FULFILLMENT", "FULFILLMENT", "EXPIRED", "ARCHIVE", "TERMINATED", "ARCHIVE");
        expected.forEach((status, stage) -> {
            jdbc.update("UPDATE contract_case SET status=? WHERE id=1", status);
            service.evict(1L);
            assertThat(service.workflow(1L).get("stage")).as(status).isEqualTo(stage);
            assertThat(listRow().get("stage")).as(status + " list").isEqualTo(stage);
        });
    }

    @Test
    void failedTasksOfferExistingRecoveryActions() {
        jdbc.update("INSERT INTO agent_run VALUES(1,1,'CONTRACT_CASE','CONTRACT_ELEMENT_EXTRACTION','FAILED')");
        assertThat(action().get("type")).isEqualTo("CONFIRM_ELEMENTS");
        snapshot("CONFIRMED");
        jdbc.update("INSERT INTO contract_analysis_workflow VALUES(1,1,'FAILED')");
        service.evict(1L);
        assertThat(action().get("type")).isEqualTo("CONFIRM_TIMELINE");
    }

    @Test
    void lowQualityIsBlockedAndCanReplaceTheDocument() {
        jdbc.update("UPDATE contract_document SET parse_quality='LOW'");
        assertThat(service.workflow(1L).get("blockedReason")).isEqualTo("QUALITY_LOW");
        assertThat(action().get("type")).isEqualTo("RETRY_PARSE");
    }

    @Test
    void riskReviewCanStartOrRetryWithoutOpeningAdvancedOperations() {
        snapshot("CONFIRMED");
        jdbc.update("INSERT INTO contract_analysis_workflow VALUES(1,1,'COMPLETED')");
        jdbc.update("INSERT INTO contract_timeline_node VALUES(1,1,'AGENT_FINAL',0,'CONFIRMED')");
        assertThat(action().get("type")).isEqualTo("HANDLE_FINDINGS");
        assertThat(action().get("label")).isEqualTo("开始风险审查");
        jdbc.update("INSERT INTO agent_run VALUES(1,1,'CONTRACT_CASE','CONTRACT_REVIEW','FAILED')");
        service.evict(1L);
        assertThat(service.workflow(1L).get("blockedReason")).isEqualTo("REVIEW_FAILED");
        assertThat(action().get("label")).isEqualTo("重新风险审查");
    }

    @Test
    void riskCountsOnlyFindingsFromLatestDeliveredReviewLikeCaseDetail() {
        snapshot("CONFIRMED");
        jdbc.update("INSERT INTO contract_timeline_node VALUES(1,1,'AGENT_FINAL',0,'CONFIRMED')");
        jdbc.update("INSERT INTO agent_run VALUES(1,1,'CONTRACT_CASE','CONTRACT_REVIEW','COMPLETED'),"
                + "(2,1,'CONTRACT_CASE','CONTRACT_REVIEW','COMPLETED')");
        jdbc.update("INSERT INTO contract_review_finding VALUES(1,1,1,'OPEN'),(2,1,2,'REMEDIATED')");
        assertThat(detail(service.workflow(1L)).get("summary")).isNotEqualTo("待法务处置 1 项风险");
        jdbc.update("INSERT INTO contract_review_finding VALUES(3,1,2,'OPEN'),(4,1,2,'OPEN')");
        service.evict(1L);
        assertThat(detail(service.workflow(1L)).get("summary")).isEqualTo("待法务处置 2 项风险");
        assertThat(listRow().get("stageOwnerRole")).isEqualTo("法务");
    }

    private void snapshot(String status) {
        jdbc.update("INSERT INTO contract_extraction_snapshot VALUES(20,1,10,?)", status);
    }

    private Map<String, Object> listRow() {
        Map<String, Object> row = new HashMap<>(Map.of("id", 1L));
        service.attachStages(new ArrayList<>(List.of(row)));
        return row;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> detail(Map<String, Object> result) {
        return (Map<String, Object>) result.get("currentDetail");
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> action() {
        return (Map<String, Object>) service.workflow(1L).get("nextAction");
    }
}
