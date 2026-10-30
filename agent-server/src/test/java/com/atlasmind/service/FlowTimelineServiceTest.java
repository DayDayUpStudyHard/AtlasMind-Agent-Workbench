package com.atlasmind.service;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.atlasmind.service.ContractFlowConstants.*;
import static org.assertj.core.api.Assertions.assertThat;

/**
 * 时间轴测试：里程碑推导（纯函数）+ 游标分页（真 MySQL）。
 *
 * <p>里程碑不查库，直接对事件序列断言；分页用与线上相同的 V041 DDL，
 * 重点验证 {@code (created_at, id)} 游标在同一秒多条事件时不漏不重。
 */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class FlowTimelineServiceTest {

    private FlowTestDatabase db;
    private FlowTimelineService service;
    private Long caseId;

    @BeforeAll
    void startDatabase() {
        db = FlowTestDatabase.start();
        service = new FlowTimelineService(db.jdbc());
    }

    @AfterAll
    void stopDatabase() {
        if (db != null) {
            db.close();
        }
    }

    @BeforeEach
    void seed() {
        db.reset();
        db.jdbc().update("INSERT INTO contract_case(status) VALUES('READY_FOR_REVIEW')");
        caseId = db.jdbc().queryForObject("SELECT MAX(id) FROM contract_case", Long.class);
    }

    // ══════════════════════════════════════════════════════════════
    // 里程碑推导（§2.3）
    // ══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("无流程：8 个刻度全部 INACTIVE")
    void emptyFlowAllInactive() {
        List<Map<String, Object>> milestones =
                FlowTimelineService.deriveMilestones(List.of());
        assertThat(milestones).hasSize(8);
        assertThat(milestones).extracting(m -> m.get("state"))
                .containsOnly("INACTIVE");
    }

    @Test
    @DisplayName("流程开始后：①②DONE，③~⑥PENDING，⑦⑧INACTIVE")
    void flowStartMilestones() {
        List<Map<String, Object>> milestones = FlowTimelineService.deriveMilestones(
                List.of(event(EV_FLOW_START, NODE_UPLOADER, null, "2026-10-30T09:00:00")));
        assertThat(states(milestones)).containsExactly(
                "DONE", "DONE", "PENDING", "PENDING", "PENDING", "PENDING",
                "INACTIVE", "INACTIVE");
    }

    @Test
    @DisplayName("确认要素/日程后 ③④ DONE")
    void confirmationsCompleteMilestones() {
        List<Map<String, Object>> milestones = FlowTimelineService.deriveMilestones(List.of(
                event(EV_FLOW_START, NODE_UPLOADER, null, "2026-10-30T09:00:00"),
                event(EV_CONFIRM_ELEMENTS, NODE_UPLOADER, null, "2026-10-30T09:10:00"),
                event(EV_CONFIRM_TIMELINE, NODE_UPLOADER, null, "2026-10-30T09:20:00")));
        assertThat(states(milestones)).containsExactly(
                "DONE", "DONE", "DONE", "DONE", "PENDING", "PENDING",
                "INACTIVE", "INACTIVE");
    }

    @Test
    @DisplayName("AGENT_RUN 完成 → ⑤ACTIVE（不等 ENTER）")
    void agentRunActivatesRiskDisposal() {
        List<Map<String, Object>> milestones = FlowTimelineService.deriveMilestones(List.of(
                event(EV_FLOW_START, NODE_UPLOADER, null, "2026-10-30T09:00:00"),
                event(EV_AGENT_RUN, NODE_AGENT, null, "2026-10-30T09:30:00")));
        assertThat(milestones.get(4).get("state")).isEqualTo("ACTIVE");
        assertThat(milestones.get(4).get("at")).isEqualTo("2026-10-30T09:30:00");
    }

    @Test
    @DisplayName("ENTER(DEPT/LEGAL) → ⑤WAITING_HUMAN；APPROVE(LEGAL) → ⑤DONE")
    void approvalMilestones() {
        List<Map<String, Object>> dept = FlowTimelineService.deriveMilestones(List.of(
                event(EV_FLOW_START, NODE_UPLOADER, null, "2026-10-30T09:00:00"),
                event(EV_AGENT_RUN, NODE_AGENT, null, "2026-10-30T09:30:00"),
                event(EV_ENTER, NODE_DEPT_APPROVAL, NODE_DEPT_APPROVAL, "2026-10-30T09:31:00")));
        assertThat(dept.get(4).get("state")).isEqualTo("WAITING_HUMAN");

        List<Map<String, Object>> legal = FlowTimelineService.deriveMilestones(List.of(
                event(EV_FLOW_START, NODE_UPLOADER, null, "2026-10-30T09:00:00"),
                event(EV_ENTER, NODE_LEGAL_APPROVAL, NODE_LEGAL_APPROVAL, "2026-10-30T10:00:00")));
        assertThat(legal.get(4).get("state")).isEqualTo("WAITING_HUMAN");
        assertThat(legal.get(4).get("at")).isEqualTo("2026-10-30T10:00:00");

        List<Map<String, Object>> approved = FlowTimelineService.deriveMilestones(List.of(
                event(EV_FLOW_START, NODE_UPLOADER, null, "2026-10-30T09:00:00"),
                event(EV_ENTER, NODE_LEGAL_APPROVAL, NODE_LEGAL_APPROVAL, "2026-10-30T10:00:00"),
                event(EV_APPROVE, NODE_LEGAL_APPROVAL, null, "2026-10-30T10:30:00")));
        assertThat(approved.get(4).get("state")).isEqualTo("DONE");
        assertThat(approved.get(5).get("state")).isEqualTo("PENDING");
    }

    @Test
    @DisplayName("SIGN_UPLOAD → ⑥ACTIVE；COMPLETE → ⑥DONE")
    void signingMilestones() {
        List<Map<String, Object>> uploaded = FlowTimelineService.deriveMilestones(List.of(
                event(EV_FLOW_START, NODE_UPLOADER, null, "2026-10-30T09:00:00"),
                event(EV_SIGN_UPLOAD, NODE_SIGNING, null, "2026-10-30T11:00:00")));
        assertThat(uploaded.get(5).get("state")).isEqualTo("ACTIVE");

        List<Map<String, Object>> complete = FlowTimelineService.deriveMilestones(List.of(
                event(EV_FLOW_START, NODE_UPLOADER, null, "2026-10-30T09:00:00"),
                event(EV_SIGN_UPLOAD, NODE_SIGNING, null, "2026-10-30T11:00:00"),
                event(EV_COMPLETE, NODE_SIGNING, null, "2026-10-30T11:30:00")));
        assertThat(complete.get(5).get("state")).isEqualTo("DONE");
        // ⑦⑧ 二期恒为未激活
        assertThat(complete.get(6).get("state")).isEqualTo("INACTIVE");
        assertThat(complete.get(7).get("state")).isEqualTo("INACTIVE");
    }

    // ══════════════════════════════════════════════════════════════
    // 游标分页（决策 19）
    // ══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("同一秒多条事件：按 (created_at,id) 翻页不漏不重")
    void cursorPaginatesEventsWithinSameSecond() {
        Long flowId = insertFlow(1);
        Timestamp same = Timestamp.valueOf(LocalDateTime.now().withNano(0));
        List<Long> inserted = new ArrayList<>();
        for (int i = 0; i < 5; i++) {
            inserted.add(insertEvent(flowId, EV_EDIT, same));
        }

        List<Long> seen = new ArrayList<>();
        String cursor = null;
        for (int page = 0; page < 3; page++) {
            Map<String, Object> result = service.timeline(caseId, cursor, 2);
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> events = (List<Map<String, Object>>) result.get("events");
            for (Map<String, Object> e : events) {
                seen.add(((Number) e.get("id")).longValue());
            }
            cursor = (String) result.get("nextCursor");
            if (cursor == null) break;
        }
        assertThat(seen).hasSize(5).doesNotHaveDuplicates();
        assertThat(seen).isSortedAccordingTo((a, b) -> Long.compare(b, a));
        assertThat(seen).containsExactlyInAnyOrderElementsOf(inserted);
    }

    @Test
    @DisplayName("跨轮次事件统一排序，并带 roundNo")
    void timelineCoversAllRounds() {
        Long round1 = insertFlow(1);
        Long round2 = insertFlow(2);
        insertEvent(round1, EV_FLOW_START, Timestamp.valueOf("2026-10-30 09:00:00"));
        insertEvent(round2, EV_FLOW_START, Timestamp.valueOf("2026-10-30 10:00:00"));

        Map<String, Object> result = service.timeline(caseId, null, 50);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> events = (List<Map<String, Object>>) result.get("events");
        assertThat(events).hasSize(2);
        assertThat(events.get(0).get("roundNo")).isEqualTo(2);
        assertThat(events.get(1).get("roundNo")).isEqualTo(1);
        // 里程碑只取当前轮（round 2）
        assertThat(result.get("roundNo")).isEqualTo(2);
    }

    @Test
    @DisplayName("非法游标返回参数错误")
    void invalidCursorRejected() {
        org.assertj.core.api.Assertions.assertThatThrownBy(
                        () -> service.timeline(caseId, "not-a-cursor", 10))
                .isInstanceOf(IllegalArgumentException.class);
    }

    // ══════════════════════════════════════════════════════════════
    // helpers
    // ══════════════════════════════════════════════════════════════

    private static List<String> states(List<Map<String, Object>> milestones) {
        return milestones.stream().map(m -> String.valueOf(m.get("state"))).toList();
    }

    private static Map<String, Object> event(String type, String nodeKey, String toNode, String at) {
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("event_type", type);
        e.put("node_key", nodeKey);
        e.put("from_node", null);
        e.put("to_node", toNode);
        e.put("created_at", Timestamp.valueOf(LocalDateTime.parse(at)));
        return e;
    }

    private Long insertFlow(int round) {
        db.jdbc().update("""
                INSERT INTO contract_flow(case_id,round_no,state,version_id,start_node,
                    baseline_json,baseline_hash)
                VALUES(?,?,'RUNNING',1,'UPLOADER','{}',REPEAT('a',64))
                """, caseId, round);
        Long flowId = db.jdbc().queryForObject("SELECT MAX(id) FROM contract_flow", Long.class);
        db.jdbc().update("""
                INSERT INTO contract_flow_node(flow_id,node_key,seq,state,entered_at)
                VALUES(?,?,0,'PENDING',NOW())
                """, flowId, NODE_UPLOADER);
        return flowId;
    }

    private Long insertEvent(Long flowId, String type, Timestamp at) {
        Long nodeId = db.jdbc().queryForObject(
                "SELECT MIN(id) FROM contract_flow_node WHERE flow_id=?", Long.class, flowId);
        db.jdbc().update("""
                INSERT INTO contract_flow_event(flow_id,node_id,event_type,actor_type,created_at)
                VALUES(?,?,?,'USER',?)
                """, flowId, nodeId, type, at);
        return db.jdbc().queryForObject(
                "SELECT MAX(id) FROM contract_flow_event WHERE flow_id=?", Long.class, flowId);
    }
}
