package com.atlasmind.service;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.atlasmind.service.ContractFlowConstants.*;

/**
 * 二期时间轴查询（只读，design §2.3 / 决策 19）。
 *
 * <p>时间轴 = 里程碑（①~⑥ 由事件推导，⑦⑧ 恒为未激活）+ 事件流（按
 * {@code (created_at, id)} 联合游标翻页，跨轮次统一排序）。
 * 仓储层不缓存：里程碑查询命中 {@code idx_flow_type}，结果不超过 8 行。
 */
@Service
@RequiredArgsConstructor
public class FlowTimelineService {

    private static final DateTimeFormatter TS = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss");
    private static final int MAX_LIMIT = 200;

    private final JdbcTemplate jdbc;

    /** 阶段定义，顺序即 ①~⑧。 */
    private static final List<Stage> STAGES = List.of(
            new Stage("INTAKE", "受理建档"),
            new Stage("PARSE", "解析就绪"),
            new Stage("ELEMENT_CONFIRM", "要素确认"),
            new Stage("TIMELINE_CONFIRM", "日程确认"),
            new Stage("RISK_DISPOSAL", "风险处置"),
            new Stage("SIGNING", "签署"),
            new Stage("FULFILLMENT", "履约跟踪"),
            new Stage("ARCHIVE", "归档续签"));

    /** 事件列表需要展示的字段；不返回原始 node_id，前端只关心 node_key。 */
    private static final String EVENT_SELECT = """
            SELECT e.id, e.flow_id, f.round_no, e.event_type, e.actor_id, e.actor_type,
                   n.node_key, e.from_node, e.to_node, e.payload_json, e.ref_id, e.created_at
            FROM contract_flow_event e
            JOIN contract_flow f ON f.id = e.flow_id
            LEFT JOIN contract_flow_node n ON n.id = e.node_id
            """;

    /**
     * 查询时间轴。
     *
     * @param caseId 案件
     * @param cursor {@code "<epochMillis>:<eventId>"}，空则从最新开始
     * @param limit  每页条数，1~200
     */
    public Map<String, Object> timeline(Long caseId, String cursor, Integer limit) {
        int size = limit == null ? 50 : Math.max(1, Math.min(MAX_LIMIT, limit));

        Map<String, Object> out = new LinkedHashMap<>();
        Map<String, Object> flow = currentFlow(caseId);
        Long flowId = flow == null ? null : asLong(flow.get("id"));
        out.put("flowId", flowId);
        out.put("roundNo", flow == null ? null : flow.get("round_no"));

        // 里程碑只覆盖当前轮；历史案件无 flow 时全部未激活
        List<Map<String, Object>> eventsForMilestones = flowId == null
                ? List.of()
                : jdbc.queryForList("""
                        SELECT event_type, node_key, from_node, to_node, created_at
                        FROM contract_flow_event e
                        LEFT JOIN contract_flow_node n ON n.id = e.node_id
                        WHERE e.flow_id=?
                        ORDER BY e.created_at ASC, e.id ASC
                        """, flowId);
        out.put("milestones", deriveMilestones(eventsForMilestones));

        // 事件列表：跨轮次统一按 (created_at, id) 倒序，游标翻页
        List<Object> args = new ArrayList<>();
        StringBuilder sql = new StringBuilder(EVENT_SELECT).append(" WHERE f.case_id=?");
        args.add(caseId);
        Cursor parsed = Cursor.parse(cursor);
        if (parsed != null) {
            sql.append(" AND (e.created_at < ? OR (e.created_at = ? AND e.id < ?))");
            args.add(parsed.createdAt());
            args.add(parsed.createdAt());
            args.add(parsed.id());
        }
        sql.append(" ORDER BY e.created_at DESC, e.id DESC LIMIT ?");
        args.add(size + 1);

        List<Map<String, Object>> rows = jdbc.queryForList(sql.toString(), args.toArray());
        boolean hasMore = rows.size() > size;
        List<Map<String, Object>> page = hasMore ? rows.subList(0, size) : rows;

        List<Map<String, Object>> events = new ArrayList<>(page.size());
        for (Map<String, Object> row : page) {
            events.add(eventView(row));
        }
        out.put("events", events);
        out.put("nextCursor", hasMore && !page.isEmpty()
                ? Cursor.of(page.get(page.size() - 1)).encode() : null);
        return out;
    }

    private Map<String, Object> currentFlow(Long caseId) {
        List<Map<String, Object>> running = jdbc.queryForList("""
                SELECT * FROM contract_flow WHERE case_id=? AND state=? ORDER BY round_no DESC LIMIT 1
                """, caseId, FLOW_RUNNING);
        if (!running.isEmpty()) {
            return running.get(0);
        }
        // 已结束的流程仍要能展示时间轴：取最新一轮
        List<Map<String, Object>> latest = jdbc.queryForList("""
                SELECT * FROM contract_flow WHERE case_id=? ORDER BY round_no DESC LIMIT 1
                """, caseId);
        return latest.isEmpty() ? null : latest.get(0);
    }

    private Map<String, Object> eventView(Map<String, Object> row) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", asLong(row.get("id")));
        view.put("flowId", asLong(row.get("flow_id")));
        view.put("roundNo", row.get("round_no"));
        view.put("eventType", row.get("event_type"));
        view.put("actorId", asLong(row.get("actor_id")));
        view.put("actorType", row.get("actor_type"));
        view.put("nodeKey", row.get("node_key"));
        view.put("fromNode", row.get("from_node"));
        view.put("toNode", row.get("to_node"));
        view.put("payload", row.get("payload_json"));
        view.put("refId", asLong(row.get("ref_id")));
        view.put("createdAt", format(row.get("created_at")));
        return view;
    }

    /**
     * 里程碑推导（design §2.3）。
     *
     * <ul>
     *   <li>① {@code FLOW_START} → DONE</li>
     *   <li>② 能开轮次说明主合同已上传并解析，{@code FLOW_START} 后即 DONE</li>
     *   <li>③ {@code CONFIRM_ELEMENTS} → DONE</li>
     *   <li>④ {@code CONFIRM_TIMELINE} → DONE</li>
     *   <li>⑤ {@code AGENT_RUN} → ACTIVE；{@code ENTER(DEPT/LEGAL)} → WAITING_HUMAN；
     *       {@code APPROVE(LEGAL_APPROVAL)} → DONE</li>
     *   <li>⑥ {@code SIGN_UPLOAD} → ACTIVE；{@code COMPLETE} → DONE</li>
     *   <li>⑦⑧ 二期无事件来源，恒为 INACTIVE</li>
     * </ul>
     *
     * <p>纯函数：只依赖事件序列，方便单测。
     */
    static List<Map<String, Object>> deriveMilestones(List<Map<String, Object>> events) {
        if (events == null || events.isEmpty()) {
            // 历史案件 / 无流程：8 个刻度全部未激活，不伪造进度
            return inactiveMilestones();
        }
        Map<String, Object> intakeAt = null;
        Map<String, Object> elementsAt = null;
        Map<String, Object> timelineAt = null;
        Map<String, Object> agentRunAt = null;
        Map<String, Object> deptEnterAt = null;
        Map<String, Object> legalEnterAt = null;
        Map<String, Object> legalApproveAt = null;
        Map<String, Object> signUploadAt = null;
        Map<String, Object> completeAt = null;

        for (Map<String, Object> e : events) {
            String type = str(e.get("event_type"));
            String nodeKey = str(e.get("node_key"));
            String toNode = str(e.get("to_node"));
            switch (type) {
                case EV_FLOW_START -> intakeAt = firstNonNull(intakeAt, e);
                case EV_CONFIRM_ELEMENTS -> elementsAt = firstNonNull(elementsAt, e);
                case EV_CONFIRM_TIMELINE -> timelineAt = firstNonNull(timelineAt, e);
                case EV_AGENT_RUN -> agentRunAt = firstNonNull(agentRunAt, e);
                case EV_ENTER -> {
                    String entered = toNode == null ? nodeKey : toNode;
                    if (NODE_DEPT_APPROVAL.equals(entered)) deptEnterAt = firstNonNull(deptEnterAt, e);
                    if (NODE_LEGAL_APPROVAL.equals(entered)) legalEnterAt = firstNonNull(legalEnterAt, e);
                }
                case EV_APPROVE -> {
                    if (NODE_LEGAL_APPROVAL.equals(nodeKey)) legalApproveAt = firstNonNull(legalApproveAt, e);
                }
                case EV_SIGN_UPLOAD -> signUploadAt = firstNonNull(signUploadAt, e);
                case EV_COMPLETE -> completeAt = firstNonNull(completeAt, e);
                default -> { }
            }
        }

        boolean started = intakeAt != null;

        List<Map<String, Object>> out = new ArrayList<>(STAGES.size());
        for (int i = 0; i < STAGES.size(); i++) {
            Stage stage = STAGES.get(i);
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("key", stage.key());
            m.put("index", i + 1);
            m.put("label", stage.label());
            String state;
            Object at = null;
            switch (i) {
                case 0 -> { state = started ? "DONE" : "PENDING"; at = timeOf(intakeAt); }
                // ① 能开轮次说明主合同已经存在并完成解析（§2.3 未单列 ② 事件）
                case 1 -> { state = started ? "DONE" : "PENDING"; at = timeOf(intakeAt); }
                case 2 -> { state = elementsAt != null ? "DONE" : "PENDING"; at = timeOf(elementsAt); }
                case 3 -> { state = timelineAt != null ? "DONE" : "PENDING"; at = timeOf(timelineAt); }
                case 4 -> {
                    if (legalApproveAt != null) { state = "DONE"; at = timeOf(legalApproveAt); }
                    else if (legalEnterAt != null) { state = "WAITING_HUMAN"; at = timeOf(legalEnterAt); }
                    else if (deptEnterAt != null) { state = "WAITING_HUMAN"; at = timeOf(deptEnterAt); }
                    else if (agentRunAt != null) { state = "ACTIVE"; at = timeOf(agentRunAt); }
                    else { state = "PENDING"; }
                }
                case 5 -> {
                    if (completeAt != null) { state = "DONE"; at = timeOf(completeAt); }
                    else if (signUploadAt != null) { state = "ACTIVE"; at = timeOf(signUploadAt); }
                    else { state = "PENDING"; }
                }
                default -> state = "INACTIVE"; // ⑦ 履约 / ⑧ 归档 属三期
            }
            m.put("state", state);
            m.put("at", at);
            out.add(m);
        }
        return out;
    }

    private static List<Map<String, Object>> inactiveMilestones() {
        List<Map<String, Object>> out = new ArrayList<>(STAGES.size());
        for (int i = 0; i < STAGES.size(); i++) {
            Stage stage = STAGES.get(i);
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("key", stage.key());
            m.put("index", i + 1);
            m.put("label", stage.label());
            m.put("state", "INACTIVE");
            m.put("at", null);
            out.add(m);
        }
        return out;
    }

    private static Map<String, Object> firstNonNull(Map<String, Object> current,
                                                    Map<String, Object> event) {
        return current != null ? current : event;
    }

    private static Object timeOf(Map<String, Object> event) {
        return event == null ? null : format(event.get("created_at"));
    }

    private static String str(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private static Long asLong(Object value) {
        if (value == null) return null;
        if (value instanceof Number n) return n.longValue();
        return Long.valueOf(String.valueOf(value));
    }

    private static String format(Object value) {
        if (value == null) return null;
        if (value instanceof LocalDateTime dt) return dt.format(TS);
        if (value instanceof java.sql.Timestamp ts) return ts.toLocalDateTime().format(TS);
        return String.valueOf(value);
    }

    private record Stage(String key, String label) {
    }

    /** {@code (created_at, id)} 联合游标（决策 19）。 */
    record Cursor(LocalDateTime createdAt, Long id) {

        static Cursor parse(String raw) {
            if (raw == null || raw.isBlank()) return null;
            int sep = raw.indexOf(':');
            if (sep <= 0) {
                throw new IllegalArgumentException("游标格式错误，应为 <epochMillis>:<id>");
            }
            long millis = Long.parseLong(raw.substring(0, sep));
            long id = Long.parseLong(raw.substring(sep + 1));
            return new Cursor(
                    LocalDateTime.ofInstant(java.time.Instant.ofEpochMilli(millis),
                            java.time.ZoneId.systemDefault()), id);
        }

        static Cursor of(Map<String, Object> row) {
            Object created = row.get("created_at");
            LocalDateTime dt;
            if (created instanceof LocalDateTime ldt) dt = ldt;
            else if (created instanceof java.sql.Timestamp ts) dt = ts.toLocalDateTime();
            else throw new IllegalStateException("created_at 类型异常: " + created);
            return new Cursor(dt, asLong(row.get("id")));
        }

        String encode() {
            long millis = createdAt.atZone(java.time.ZoneId.systemDefault())
                    .toInstant().toEpochMilli();
            return millis + ":" + id;
        }
    }
}
