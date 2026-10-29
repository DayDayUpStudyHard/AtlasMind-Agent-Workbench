package com.atlasmind.service;

import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 一期阶段推导规则的单测：纯函数推导，不打数据库。
 * 规则真源：docs/contract-workflow/phase-1-workflow-view.md §5。
 */
class ContractWorkflowServiceTest {

    @Test
    void draftWithoutDocumentStopsAtIntake() {
        ContractWorkflowService.Signals s = new ContractWorkflowService.Signals();
        s.caseStatus = "DRAFT";
        s.createdAt = LocalDateTime.of(2026, 10, 20, 9, 12);

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 1L);

        assertThat(result.get("stage")).isEqualTo("INTAKE");
        assertThat(result.get("stageIndex")).isEqualTo(1);
        assertThat(stateOf(result, "INTAKE")).isEqualTo("WAITING_HUMAN");
        assertThat(nextActionType(result)).isEqualTo("UPLOAD_DOCUMENT");
        assertThat(enteredAtOf(result, "INTAKE")).isEqualTo("2026-10-20T09:12");
        // ③~⑧ 一律 null
        assertThat(enteredAtOf(result, "ELEMENT_CONFIRM")).isNull();
    }

    @Test
    void parsingDocumentIsActiveAtParseStage() {
        ContractWorkflowService.Signals s = new ContractWorkflowService.Signals();
        s.caseStatus = "INTAKE_PARSING";
        s.hasMainDocument = true;
        s.parseStatus = "PARSING";

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 2L);

        assertThat(stateOf(result, "INTAKE")).isEqualTo("DONE");
        assertThat(stateOf(result, "PARSE")).isEqualTo("ACTIVE");
        assertThat(result.get("stage")).isEqualTo("PARSE");
        assertThat(nextActionType(result)).isEqualTo("NONE");
    }

    @Test
    void parseFailureIsBlockedWithReasonCode() {
        ContractWorkflowService.Signals s = new ContractWorkflowService.Signals();
        s.hasMainDocument = true;
        s.parseStatus = "FAILED";
        s.caseStatus = "INTAKE_PARSING";

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 3L);

        assertThat(stateOf(result, "PARSE")).isEqualTo("BLOCKED");
        assertThat(blockedReason(result)).isEqualTo("PARSE_FAILED");
        assertThat(nextActionType(result)).isEqualTo("RETRY_PARSE");
    }

    @Test
    void lowQualityParseBlocksForHumanRelease() {
        ContractWorkflowService.Signals s = new ContractWorkflowService.Signals();
        s.hasMainDocument = true;
        s.parseStatus = "READY";
        s.parseQuality = "LOW";

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 4L);

        assertThat(stateOf(result, "PARSE")).isEqualTo("BLOCKED");
        assertThat(blockedReason(result)).isEqualTo("QUALITY_LOW");
    }

    @Test
    void parsedWithoutExtractionOffersExtractionAction() {
        ContractWorkflowService.Signals s = new ContractWorkflowService.Signals();
        s.hasMainDocument = true;
        s.parseStatus = "READY";
        s.parseQuality = "HIGH";
        s.caseStatus = "READY_FOR_REVIEW";

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 5L);

        assertThat(stateOf(result, "PARSE")).isEqualTo("DONE");
        assertThat(stateOf(result, "ELEMENT_CONFIRM")).isEqualTo("PENDING");
        assertThat(result.get("stage")).isEqualTo("ELEMENT_CONFIRM");
        assertThat(nextActionType(result)).isEqualTo("CONFIRM_ELEMENTS");
    }

    @Test
    void snapshotReadyForConfirmationWaitsForBusinessOwner() {
        ContractWorkflowService.Signals s = baseParsed();
        s.snapshotStatus = "READY_FOR_CONFIRMATION";

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 6L);

        assertThat(stateOf(result, "ELEMENT_CONFIRM")).isEqualTo("WAITING_HUMAN");
        assertThat(ownerRoleOf(result, "ELEMENT_CONFIRM")).isEqualTo("业务负责人");
        assertThat(nextActionType(result)).isEqualTo("CONFIRM_ELEMENTS");
    }

    @Test
    void confirmedSnapshotMovesOnToTimeline() {
        ContractWorkflowService.Signals s = baseParsed();
        s.snapshotStatus = "CONFIRMED";
        s.timelineTotal = 12;
        s.timelinePending = 3;

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 7L);

        assertThat(stateOf(result, "ELEMENT_CONFIRM")).isEqualTo("DONE");
        assertThat(stateOf(result, "TIMELINE_CONFIRM")).isEqualTo("WAITING_HUMAN");
        assertThat(result.get("stage")).isEqualTo("TIMELINE_CONFIRM");
        assertThat(nextActionType(result)).isEqualTo("CONFIRM_TIMELINE");

        @SuppressWarnings("unchecked")
        Map<String, Object> counters = (Map<String, Object>) ((Map<String, Object>) result.get("currentDetail"))
                .get("counters");
        assertThat(counters.get("total")).isEqualTo(12);
        assertThat(counters.get("confirmed")).isEqualTo(9);
        assertThat(counters.get("pending")).isEqualTo(3);
    }

    @Test
    void allTimelineNodesReviewedCompletesTimelineStage() {
        ContractWorkflowService.Signals s = baseParsed();
        s.snapshotStatus = "CONFIRMED";
        s.timelineTotal = 5;
        s.timelinePending = 0;
        s.hasReviewRun = false;

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 8L);

        assertThat(stateOf(result, "TIMELINE_CONFIRM")).isEqualTo("DONE");
        assertThat(result.get("stage")).isEqualTo("RISK_DISPOSAL");
        assertThat(stateOf(result, "RISK_DISPOSAL")).isEqualTo("PENDING");
    }

    @Test
    void openFindingsWaitForLegal() {
        ContractWorkflowService.Signals s = riskReady();
        s.openFindings = 4;

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 9L);

        assertThat(stateOf(result, "RISK_DISPOSAL")).isEqualTo("WAITING_HUMAN");
        assertThat(ownerRoleOf(result, "RISK_DISPOSAL")).isEqualTo("法务");
        assertThat(nextActionType(result)).isEqualTo("HANDLE_FINDINGS");
        assertThat(summaryOf(result)).contains("4");
    }

    @Test
    void limitedReviewIsFlagged() {
        ContractWorkflowService.Signals s = riskReady();
        s.reviewRunStatus = "LIMITED";
        s.reviewLimited = true;

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 10L);

        assertThat(stateOf(result, "RISK_DISPOSAL")).isEqualTo("WAITING_HUMAN");
        assertThat(result.get("limited")).isEqualTo(true);
    }

    @Test
    void pendingApprovalShowsBuildInProgressCopyWithoutApproveAction() {
        ContractWorkflowService.Signals s = riskReady();
        s.reviewRunStatus = "COMPLETED";
        s.caseStatus = "PENDING_APPROVAL";

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 11L);

        assertThat(stateOf(result, "RISK_DISPOSAL")).isEqualTo("WAITING_HUMAN");
        assertThat(nextActionType(result)).isEqualTo("NONE");
        assertThat(summaryOf(result)).contains("审批功能建设中");
        // 一期不产生审批动作
        assertThat(nextActionType(result)).isNotEqualTo("APPROVE");
    }

    @Test
    void approvedWaitsForOfflineSigning() {
        ContractWorkflowService.Signals s = riskReady();
        s.reviewRunStatus = "COMPLETED";
        s.caseStatus = "APPROVED";

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 12L);

        assertThat(stateOf(result, "RISK_DISPOSAL")).isEqualTo("DONE");
        assertThat(stateOf(result, "SIGNING")).isEqualTo("WAITING_HUMAN");
        assertThat(ownerRoleOf(result, "SIGNING")).isEqualTo("发起人");
        assertThat(nextActionType(result)).isEqualTo("NONE");
        assertThat(result.get("stage")).isEqualTo("SIGNING");
    }

    @Test
    void signedMovesFulfillmentToPendingNotDone() {
        ContractWorkflowService.Signals s = riskReady();
        s.reviewRunStatus = "COMPLETED";
        s.caseStatus = "SIGNED";

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 13L);

        assertThat(stateOf(result, "SIGNING")).isEqualTo("DONE");
        assertThat(stateOf(result, "FULFILLMENT")).isEqualTo("PENDING");
        assertThat(result.get("stage")).isEqualTo("FULFILLMENT");
    }

    @Test
    void inFulfillmentWaitsForOwnerWithoutReadingObligations() {
        ContractWorkflowService.Signals s = riskReady();
        s.reviewRunStatus = "COMPLETED";
        s.caseStatus = "IN_FULFILLMENT";

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 14L);

        assertThat(stateOf(result, "FULFILLMENT")).isEqualTo("WAITING_HUMAN");
        assertThat(ownerRoleOf(result, "FULFILLMENT")).isEqualTo("业务负责人");
        assertThat(nextActionType(result)).isEqualTo("NONE");
    }

    @Test
    void expiredIsOverdueAndArchived() {
        ContractWorkflowService.Signals s = riskReady();
        s.reviewRunStatus = "COMPLETED";
        s.caseStatus = "EXPIRED";
        s.expiryDate = LocalDate.now().minusDays(30);

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 15L);

        assertThat(stateOf(result, "FULFILLMENT")).isEqualTo("DONE");
        assertThat(stateOf(result, "ARCHIVE")).isEqualTo("DONE");
        assertThat(result.get("stage")).isEqualTo("ARCHIVE");
    }

    @Test
    void onlyFirstNonDoneStageIsCurrentAndLaterStagesArePending() {
        ContractWorkflowService.Signals s = new ContractWorkflowService.Signals();
        s.hasMainDocument = true;
        s.parseStatus = "READY";
        s.snapshotStatus = "CONFIRMED";
        s.timelineTotal = 2;
        s.timelinePending = 0;
        s.openFindings = 1;

        Map<String, Object> result = ContractWorkflowService.deriveResult(s, 16L);

        assertThat(result.get("stage")).isEqualTo("RISK_DISPOSAL");
        assertThat(stateOf(result, "SIGNING")).isEqualTo("PENDING");
        assertThat(stateOf(result, "FULFILLMENT")).isEqualTo("PENDING");
        assertThat(stateOf(result, "ARCHIVE")).isEqualTo("PENDING");
    }

    @Test
    void allEightStagesUseFixedKeys() {
        Map<String, Object> result = ContractWorkflowService.deriveResult(new ContractWorkflowService.Signals(), 17L);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> stages = (List<Map<String, Object>>) result.get("stages");
        assertThat(stages).extracting(stage -> stage.get("key")).containsExactly(
                "INTAKE", "PARSE", "ELEMENT_CONFIRM", "TIMELINE_CONFIRM",
                "RISK_DISPOSAL", "SIGNING", "FULFILLMENT", "ARCHIVE");
    }

    // ── helpers ─────────────────────────────────────────────────────

    private ContractWorkflowService.Signals baseParsed() {
        ContractWorkflowService.Signals s = new ContractWorkflowService.Signals();
        s.hasMainDocument = true;
        s.parseStatus = "READY";
        s.parseQuality = "HIGH";
        s.caseStatus = "READY_FOR_REVIEW";
        return s;
    }

    private ContractWorkflowService.Signals riskReady() {
        ContractWorkflowService.Signals s = baseParsed();
        s.snapshotStatus = "CONFIRMED";
        s.timelineTotal = 3;
        s.timelinePending = 0;
        s.hasExtractionRun = true;
        s.extractionRunStatus = "COMPLETED";
        s.hasTimelineRun = true;
        s.timelineRunStatus = "COMPLETED";
        s.hasReviewRun = true;
        s.reviewRunStatus = "COMPLETED";
        return s;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> stage(Map<String, Object> result, String key) {
        List<Map<String, Object>> stages = (List<Map<String, Object>>) result.get("stages");
        return stages.stream().filter(s -> key.equals(s.get("key"))).findFirst().orElseThrow();
    }

    private Object stateOf(Map<String, Object> result, String key) {
        return stage(result, key).get("state");
    }

    private Object ownerRoleOf(Map<String, Object> result, String key) {
        return stage(result, key).get("ownerRole");
    }

    private Object enteredAtOf(Map<String, Object> result, String key) {
        return stage(result, key).get("enteredAt");
    }

    @SuppressWarnings("unchecked")
    private String nextActionType(Map<String, Object> result) {
        return String.valueOf(((Map<String, Object>) result.get("nextAction")).get("type"));
    }

    private Object blockedReason(Map<String, Object> result) {
        return result.get("blockedReason");
    }

    @SuppressWarnings("unchecked")
    private String summaryOf(Map<String, Object> result) {
        return String.valueOf(((Map<String, Object>) result.get("currentDetail")).get("summary"));
    }
}
