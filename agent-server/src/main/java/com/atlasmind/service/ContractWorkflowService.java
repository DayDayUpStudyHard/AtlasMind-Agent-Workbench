package com.atlasmind.service;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 合同案件工作流视图的唯一推导实现（一期）。
 *
 * <p>把现有数据翻译成 8 个业务阶段，供用户端、管理端和后续通知共用。
 * 只读：不写状态、不改表、不触发任务。阶段是"推断"，不是权威状态。
 *
 * <p>枚举真源：docs/contract-workflow/README.md §4。
 */
@Service
@RequiredArgsConstructor
public class ContractWorkflowService {

    /** 阶段顺序（固定枚举，前端不解析中文）。 */
    public static final List<String> STAGE_KEYS = List.of(
            "INTAKE", "PARSE", "ELEMENT_CONFIRM", "TIMELINE_CONFIRM",
            "RISK_DISPOSAL", "SIGNING", "FULFILLMENT", "ARCHIVE");

    public static final Map<String, String> STAGE_LABELS = Map.of(
            "INTAKE", "受理建档",
            "PARSE", "解析就绪",
            "ELEMENT_CONFIRM", "要素确认",
            "TIMELINE_CONFIRM", "日程确认",
            "RISK_DISPOSAL", "风险处置",
            "SIGNING", "签署",
            "FULFILLMENT", "履约跟踪",
            "ARCHIVE", "归档续签");

    public static final String DONE = "DONE";
    public static final String ACTIVE = "ACTIVE";
    public static final String WAITING_HUMAN = "WAITING_HUMAN";
    public static final String BLOCKED = "BLOCKED";
    public static final String PENDING = "PENDING";

    private static final Set<String> RUN_ACTIVE = Set.of(
            "CREATED", "CONTEXT_BUILDING", "PLANNING", "ANALYZING", "VERIFYING",
            "WAITING_HUMAN", "WAITING_APPROVAL", "RUNNING", "PENDING", "QUEUED");
    private static final Set<String> REVIEW_DONE_RUN = Set.of("COMPLETED", "LIMITED");
    private static final Set<String> SIGNED_OR_LATER = Set.of(
            "SIGNED", "IN_FULFILLMENT", "EXPIRED", "TERMINATED");
    private static final Set<String> APPROVED_OR_SIGNING = Set.of("APPROVED", "READY_TO_SIGN");
    private static final Set<String> RISK_DONE_STATUS = Set.of(
            "APPROVED", "READY_TO_SIGN", "SIGNED", "IN_FULFILLMENT", "EXPIRED", "TERMINATED");
    private static final Set<String> ARCHIVED_STATUS = Set.of("EXPIRED", "TERMINATED");

    private static final long CACHE_TTL_MS = 2_000L;
    private static final int CACHE_MAX_ENTRIES = 2_000;

    private final JdbcTemplate jdbcTemplate;
    private final Map<Long, Cached> cache = new ConcurrentHashMap<>();

    /** 详情：案件工作流视图。 */
    public Map<String, Object> workflow(Long caseId) {
        Cached cached = cache.get(caseId);
        long now = System.currentTimeMillis();
        if (cached != null && cached.expiresAt > now) return cached.result;

        Map<String, Object> result = deriveResult(loadSignals(caseId), caseId);
        if (cache.size() > CACHE_MAX_ENTRIES) cache.clear();
        cache.put(caseId, new Cached(result, now + CACHE_TTL_MS));
        return result;
    }

    /** 显式失效（用户执行下一步动作后调用，避免 2 秒缓存显示旧阶段）。 */
    public void evict(Long caseId) {
        if (caseId != null) cache.remove(caseId);
    }

    // ── 列表批量推导 ────────────────────────────────────────────────

    /**
     * 为列表行增补 stage / stageLabel / stageOwnerRole。
     * 使用固定条数的批量查询，绝不逐条查库（一期性能约束）。
     */
    public void attachStages(List<Map<String, Object>> cases) {
        if (cases == null || cases.isEmpty()) return;
        List<Long> ids = new ArrayList<>();
        for (Map<String, Object> row : cases) {
            Long id = longOrNull(row.get("id"));
            if (id != null) ids.add(id);
        }
        if (ids.isEmpty()) return;

        Map<Long, Signals> signals;
        try {
            signals = loadSignalsBatch(ids);
        } catch (Exception ignored) {
            // 旧库缺少 V025/V026 时降级：不阻断列表
            return;
        }
        for (Map<String, Object> row : cases) {
            Long id = longOrNull(row.get("id"));
            Signals s = id == null ? null : signals.get(id);
            if (s == null) continue;
            Map<String, Object> derived = deriveResult(s, id);
            row.put("stage", derived.get("stage"));
            row.put("stageLabel", STAGE_LABELS.get(String.valueOf(derived.get("stage"))));
            row.put("stageOwnerRole", ((Map<?, ?>) ((List<?>) derived.get("stages")).get(
                    ((Number) derived.get("stageIndex")).intValue() - 1)).get("ownerRole"));
        }
    }

    // ── 数据装载 ────────────────────────────────────────────────────

    private Signals loadSignals(Long caseId) {
        Signals signals = loadSignalsBatch(List.of(caseId)).get(caseId);
        if (signals == null) throw new IllegalArgumentException("合同案件不存在");
        return signals;
    }

    private Map<Long, Signals> loadSignalsBatch(Collection<Long> ids) {
        Map<Long, Signals> map = new HashMap<>();
        List<Object> params = new ArrayList<>(ids);
        String in = placeholders(ids.size());

        List<Map<String, Object>> cases = jdbcTemplate.queryForList(
                "SELECT id, status, create_time AS createTime, expiry_date AS expiryDate "
                        + "FROM contract_case WHERE deleted=0 AND id IN (" + in + ")", params.toArray());
        for (Map<String, Object> row : cases) {
            Signals s = new Signals();
            map.put(longOrNull(row.get("id")), s);
            s.caseStatus = upper(str(row.get("status")));
            s.createdAt = localDateTime(row.get("createTime"));
            s.expiryDate = localDate(row.get("expiryDate"));
        }

        try {
            List<Map<String, Object>> docs = jdbcTemplate.queryForList(
                    "SELECT case_id AS caseId, parse_status AS parseStatus, parse_quality AS parseQuality, "
                            + "create_time AS createTime FROM contract_document "
                            + "WHERE document_type='MAIN' AND COALESCE(deleted,0)=0 AND case_id IN (" + in + ") "
                            + "ORDER BY case_id, version DESC, id DESC", params.toArray());
            for (Map<String, Object> row : docs) {
                Signals s = map.get(longOrNull(row.get("caseId")));
                if (s == null || s.hasMainDocument) continue;
                s.hasMainDocument = true;
                s.parseStatus = upper(str(row.get("parseStatus")));
                s.parseQuality = upper(str(row.get("parseQuality")));
                s.mainDocumentCreatedAt = localDateTime(row.get("createTime"));
            }
        } catch (Exception ignored) { /* 滚动部署期缺列时按无文档处理 */ }

        try {
            List<Map<String, Object>> snaps = jdbcTemplate.queryForList(
                    "SELECT s.case_id AS caseId, s.status, COUNT(e.id) AS total, "
                            + "SUM(CASE WHEN e.id IS NOT NULL AND COALESCE(UPPER(e.review_status),'') "
                            + "NOT IN ('CONFIRMED','NOT_APPLICABLE') THEN 1 ELSE 0 END) AS pending "
                            + "FROM contract_extraction_snapshot s "
                            + "LEFT JOIN contract_extracted_element e ON e.snapshot_id=s.id "
                            + "WHERE s.case_id IN (" + in + ") AND s.document_id=("
                            + "SELECT d.id FROM contract_document d WHERE d.case_id=s.case_id "
                            + "AND d.document_type='MAIN' AND COALESCE(d.deleted,0)=0 "
                            + "ORDER BY d.version DESC,d.id DESC LIMIT 1) "
                            + "AND s.status IN ('READY_FOR_CONFIRMATION','CONFIRMED') "
                            + "GROUP BY s.id,s.case_id,s.status "
                            + "ORDER BY s.case_id,(s.status='CONFIRMED') DESC,s.id DESC", params.toArray());
            for (Map<String, Object> row : snaps) {
                Signals s = map.get(longOrNull(row.get("caseId")));
                if (s != null && s.snapshotStatus == null) {
                    s.snapshotStatus = upper(str(row.get("status")));
                    s.elementTotal = intOf(row.get("total"));
                    s.elementPending = intOf(row.get("pending"));
                }
            }
        } catch (Exception ignored) { /* V026 未应用 */ }

        try {
            List<Map<String, Object>> runs = jdbcTemplate.queryForList(
                    "SELECT subject_id AS caseId, run_type AS runType, status FROM agent_run "
                            + "WHERE subject_type='CONTRACT_CASE' AND subject_id IN (" + in + ") "
                            + "AND run_type IN ('CONTRACT_ELEMENT_EXTRACTION','TIMELINE_EXTRACTION','CONTRACT_REVIEW') "
                            + "ORDER BY subject_id, id DESC", params.toArray());
            for (Map<String, Object> run : runs) {
                Signals s = map.get(longOrNull(run.get("caseId")));
                if (s == null) continue;
                String type = upper(str(run.get("runType")));
                String status = upper(str(run.get("status")));
                switch (type) {
                    case "CONTRACT_ELEMENT_EXTRACTION" -> { if (!s.hasExtractionRun) { s.extractionRunStatus = status; s.hasExtractionRun = true; } }
                    case "TIMELINE_EXTRACTION" -> { if (!s.hasTimelineRun) { s.timelineRunStatus = status; s.hasTimelineRun = true; } }
                    case "CONTRACT_REVIEW" -> { if (!s.hasReviewRun) { s.reviewRunStatus = status; s.hasReviewRun = true; } }
                    default -> { }
                }
            }
        } catch (Exception ignored) { /* 无运行表 */ }

        try {
            List<Map<String, Object>> workflows = jdbcTemplate.queryForList(
                    "SELECT case_id AS caseId, timeline_status AS timelineStatus FROM contract_analysis_workflow "
                            + "WHERE case_id IN (" + in + ") ORDER BY case_id,id DESC", params.toArray());
            for (Map<String, Object> row : workflows) {
                Signals s = map.get(longOrNull(row.get("caseId")));
                if (s != null && s.timelineStatus == null) s.timelineStatus = upper(str(row.get("timelineStatus")));
            }
        } catch (Exception ignored) { /* V025 未应用 */ }

        try {
            List<Map<String, Object>> counts = jdbcTemplate.queryForList(
                    "SELECT case_id AS caseId, COUNT(*) AS total, "
                            + "SUM(CASE WHEN COALESCE(UPPER(review_status),'') IN ('CONFIRMED','NOT_APPLICABLE') "
                            + "THEN 0 ELSE 1 END) AS pending FROM contract_timeline_node "
                            + "WHERE case_id IN (" + in + ") AND (source='AGENT_FINAL' OR manual_override=1) "
                            + "GROUP BY case_id", params.toArray());
            for (Map<String, Object> row : counts) {
                Signals s = map.get(longOrNull(row.get("caseId")));
                if (s == null) continue;
                s.timelineTotal = intOf(row.get("total"));
                s.timelinePending = intOf(row.get("pending"));
            }
        } catch (Exception ignored) { /* 无时间节点表 */ }

        try {
            List<Map<String, Object>> opens = jdbcTemplate.queryForList(
                    "SELECT f.case_id AS caseId, COUNT(*) AS openCount FROM contract_review_finding f "
                            + "WHERE f.status='OPEN' AND f.case_id IN (" + in + ") "
                            + "AND f.run_id=(SELECT MAX(ar.id) FROM agent_run ar "
                            + "WHERE ar.subject_type='CONTRACT_CASE' AND ar.subject_id=f.case_id "
                            + "AND ar.run_type='CONTRACT_REVIEW' AND ar.status IN ('COMPLETED','LIMITED')) "
                            + "GROUP BY f.case_id", params.toArray());
            for (Map<String, Object> row : opens) {
                Signals s = map.get(longOrNull(row.get("caseId")));
                if (s != null) s.openFindings = intOf(row.get("openCount"));
            }
        } catch (Exception ignored) { /* 无发现表 */ }

        for (Signals s : map.values()) s.reviewLimited = "LIMITED".equals(s.reviewRunStatus);
        return map;
    }

    // ── 推导（纯函数，便于单测） ────────────────────────────────────

    static Map<String, Object> deriveResult(Signals s, Long caseId) {
        List<Stage> stages = new ArrayList<>();
        stages.add(intake(s));
        stages.add(parse(s));
        stages.add(element(s));
        stages.add(timeline(s));
        stages.add(risk(s));
        stages.add(signing(s));
        stages.add(fulfillment(s));
        stages.add(archive(s));

        // 后期业务状态是已有的明确推进信号；历史案件可能没有新版快照/日程数据。
        // 只读视图承认已有业务进度，不写状态、不凭空补业务记录。
        if (RISK_DONE_STATUS.contains(nvl(s.caseStatus))) {
            for (int i = 0; i < 5; i++) {
                Stage st = stages.get(i);
                stages.set(i, new Stage(st.key, DONE, null, st.enteredAt, null,
                        "根据案件业务状态推断已完成", null, null, false));
            }
        }

        // 只推导到第一个非 DONE 阶段，其后一律 PENDING，避免"后面完成、前面未完成"。
        int currentIndex = stages.size() - 1;
        for (int i = 0; i < stages.size(); i++) {
            if (!DONE.equals(stages.get(i).state)) { currentIndex = i; break; }
        }
        for (int i = currentIndex + 1; i < stages.size(); i++) {
            Stage st = stages.get(i);
            stages.set(i, new Stage(st.key, PENDING, st.ownerRole, null, null, null, null, null, false));
        }
        Stage current = stages.get(currentIndex);

        List<Map<String, Object>> stageViews = new ArrayList<>();
        for (Stage st : stages) {
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("key", st.key);
            view.put("label", STAGE_LABELS.get(st.key));
            view.put("state", st.state);
            view.put("ownerRole", st.ownerRole);
            view.put("enteredAt", st.enteredAt);
            stageViews.add(view);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("caseId", caseId);
        result.put("stage", current.key);
        result.put("stageLabel", STAGE_LABELS.get(current.key));
        result.put("stageIndex", currentIndex + 1);
        result.put("stages", stageViews);
        Map<String, Object> currentDetail = new LinkedHashMap<>();
        currentDetail.put("summary", current.summary == null ? "" : current.summary);
        currentDetail.put("counters", current.counters == null ? Map.of() : current.counters);
        result.put("currentDetail", currentDetail);
        Map<String, Object> nextAction = new LinkedHashMap<>();
        nextAction.put("type", current.nextActionType == null ? "NONE" : current.nextActionType);
        nextAction.put("label", current.nextActionLabel == null ? "" : current.nextActionLabel);
        nextAction.put("actorRole", current.ownerRole);
        nextAction.put("actorName", null);
        // 阻塞时仍可给出可执行动作（如 PARSE_FAILED → 重新上传），只有 NONE 才无按钮。
        nextAction.put("enabled", current.nextActionType != null && !"NONE".equals(current.nextActionType));
        result.put("nextAction", nextAction);
        result.put("blockedReason", current.blockedReason);
        result.put("limited", current.limited);
        return result;
    }

    private static Stage intake(Signals s) {
        if (!s.hasMainDocument) {
            return new Stage("INTAKE", WAITING_HUMAN, "发起人", iso(s.createdAt),
                    null, "待上传主合同", "UPLOAD_DOCUMENT", "上传主合同", false);
        }
        return new Stage("INTAKE", DONE, null, iso(s.createdAt), null, null, null, null, false);
    }

    private static Stage parse(Signals s) {
        if (!s.hasMainDocument) return pending("PARSE");
        String ps = nvl(s.parseStatus);
        if (Set.of("PENDING", "PARSING", "UPLOADED", "PROCESSING").contains(ps)) {
            return new Stage("PARSE", ACTIVE, null, iso(s.mainDocumentCreatedAt), null, "合同解析中", null, null, false);
        }
        if ("FAILED".equals(ps)) {
            return new Stage("PARSE", BLOCKED, "发起人", iso(s.mainDocumentCreatedAt), "PARSE_FAILED",
                    "合同解析失败，需要重试或换解析方式", "RETRY_PARSE", "重新上传合同", false);
        }
        if ("READY".equals(ps) && "LOW".equals(nvl(s.parseQuality))) {
            return new Stage("PARSE", BLOCKED, "业务负责人", iso(s.mainDocumentCreatedAt), "QUALITY_LOW",
                    "解析质量低，结论只能作为参考，请业务负责人核对并重新上传清晰合同", "RETRY_PARSE", "上传清晰合同", false);
        }
        if ("READY".equals(ps)) {
            return new Stage("PARSE", DONE, null, iso(s.mainDocumentCreatedAt), null, null, null, null, false);
        }
        return new Stage("PARSE", ACTIVE, null, iso(s.mainDocumentCreatedAt), null, "合同解析中", null, null, false);
    }

    private static Stage element(Signals s) {
        String snap = nvl(s.snapshotStatus);
        Map<String, Object> counters = Map.of("total", s.elementTotal,
                "confirmed", s.elementTotal - s.elementPending, "pending", s.elementPending);
        if ("CONFIRMED".equals(snap) || ("READY_FOR_CONFIRMATION".equals(snap)
                && s.elementTotal > 0 && s.elementPending == 0)) {
            return new Stage("ELEMENT_CONFIRM", DONE, null, null, null, "合同要素已确认", null, null, false, counters);
        }
        if ("READY_FOR_CONFIRMATION".equals(snap)) {
            return new Stage("ELEMENT_CONFIRM", WAITING_HUMAN, "业务负责人", null, null,
                    "合同要素已生成，" + s.elementPending + " 个字段待确认", "CONFIRM_ELEMENTS", "确认合同要素", false, counters);
        }
        if ("FAILED".equals(nvl(s.extractionRunStatus))) {
            return new Stage("ELEMENT_CONFIRM", BLOCKED, "发起人", null, "EXTRACTION_FAILED",
                    "要素提取失败，可重试", "CONFIRM_ELEMENTS", "重新提取合同要素", false);
        }
        if (RUN_ACTIVE.contains(nvl(s.extractionRunStatus))) {
            return new Stage("ELEMENT_CONFIRM", ACTIVE, null, null, null, "合同要素提取中", null, null, false);
        }
        if (!s.hasExtractionRun) {
            return new Stage("ELEMENT_CONFIRM", PENDING, "业务负责人", null, null,
                    "尚未提取合同要素", "CONFIRM_ELEMENTS", "提取合同要素", false);
        }
        return new Stage("ELEMENT_CONFIRM", PENDING, "业务负责人", null, null,
                "等待提取合同要素", "CONFIRM_ELEMENTS", "提取合同要素", false);
    }

    private static Stage timeline(Signals s) {
        String run = nvl(s.timelineRunStatus);
        String wf = nvl(s.timelineStatus);
        if ("FAILED".equals(run) || "FAILED".equals(wf)) {
            return new Stage("TIMELINE_CONFIRM", BLOCKED, "发起人", null, "TIMELINE_FAILED",
                    "履约日程生成失败，可重试", "CONFIRM_TIMELINE", "重新生成履约日程", false);
        }
        if ("RUNNING".equals(run) || "RUNNING".equals(wf) || RUN_ACTIVE.contains(run)) {
            return new Stage("TIMELINE_CONFIRM", ACTIVE, null, null, null, "履约日程生成中", null, null, false);
        }
        if (s.timelineTotal == 0) {
            return new Stage("TIMELINE_CONFIRM", PENDING, "业务负责人", null, null,
                    "尚未生成履约日程", "CONFIRM_TIMELINE", "生成履约日程", false);
        }
        Map<String, Object> counters = new LinkedHashMap<>();
        counters.put("total", s.timelineTotal);
        counters.put("confirmed", s.timelineTotal - s.timelinePending);
        counters.put("pending", s.timelinePending);
        if (s.timelinePending > 0) {
            return new Stage("TIMELINE_CONFIRM", WAITING_HUMAN, "业务负责人", null, null,
                    "已识别 " + s.timelineTotal + " 个时间节点，" + s.timelinePending + " 个待确认",
                    "CONFIRM_TIMELINE", "确认履约日程", false, counters);
        }
        return new Stage("TIMELINE_CONFIRM", DONE, null, null, null,
                "已识别 " + s.timelineTotal + " 个时间节点，全部已确认", null, null, false, counters);
    }

    private static Stage risk(Signals s) {
        String run = nvl(s.reviewRunStatus);
        String status = nvl(s.caseStatus);
        // 案件已被业务动作推进到审批/签署/履约之后，⑤ 视为已完成。
        // 否则历史遗留的 OPEN 发现会把阶段条拉回 ⑤，出现"后面完成、前面未完成"。
        if (RISK_DONE_STATUS.contains(status)) {
            return new Stage("RISK_DISPOSAL", DONE, null, null, null, "风险处置已完成", null, null, false);
        }
        if ("FAILED".equals(run)) {
            return new Stage("RISK_DISPOSAL", BLOCKED, "发起人", null, "REVIEW_FAILED",
                    "风险审查失败，可重试", "HANDLE_FINDINGS", "重新风险审查", false);
        }
        if (RUN_ACTIVE.contains(run)) {
            return new Stage("RISK_DISPOSAL", ACTIVE, null, null, null, "风险审查进行中", null, null, false);
        }
        if ("LIMITED".equals(run) || s.reviewLimited) {
            return new Stage("RISK_DISPOSAL", WAITING_HUMAN, "法务", null, null,
                    "本次审查范围受限，结论仅供参考，需人工处置", "NONE", null, true);
        }
        if (s.openFindings > 0) {
            return new Stage("RISK_DISPOSAL", WAITING_HUMAN, "法务", null, null,
                    "待法务处置 " + s.openFindings + " 项风险", "HANDLE_FINDINGS", "处置风险发现", false);
        }
        if (REVIEW_DONE_RUN.contains(run)) {
            if ("NEEDS_REVISION".equals(status)) {
                return new Stage("RISK_DISPOSAL", WAITING_HUMAN, "业务负责人", null, null,
                        "审查已退回，请按驳回意见修改或补证", "NONE", null, false);
            }
            return new Stage("RISK_DISPOSAL", WAITING_HUMAN, "审批人", null, null,
                    "审查已完成，审批功能建设中，请线下处理", "NONE", null, false);
        }
        if ("NEEDS_REVISION".equals(status)) {
            return new Stage("RISK_DISPOSAL", WAITING_HUMAN, "业务负责人", null, null,
                    "审查已退回，请按驳回意见修改或补证", "NONE", null, false);
        }
        if ("PENDING_APPROVAL".equals(status)) {
            return new Stage("RISK_DISPOSAL", WAITING_HUMAN, "审批人", null, null,
                    "审批功能建设中，请线下处理", "NONE", null, false);
        }
        return new Stage("RISK_DISPOSAL", PENDING, "法务", null, null,
                "尚未进行风险审查", "HANDLE_FINDINGS", "开始风险审查", false);
    }

    private static Stage signing(Signals s) {
        String status = nvl(s.caseStatus);
        if (APPROVED_OR_SIGNING.contains(status)) {
            return new Stage("SIGNING", WAITING_HUMAN, "发起人", null, null,
                    "已批准，待线下签署并归档签署件", "NONE", null, false);
        }
        if (SIGNED_OR_LATER.contains(status)) {
            return new Stage("SIGNING", DONE, null, null, null, "已签署", null, null, false);
        }
        return pending("SIGNING");
    }

    private static Stage fulfillment(Signals s) {
        String status = nvl(s.caseStatus);
        if ("IN_FULFILLMENT".equals(status)) {
            boolean overdue = s.expiryDate != null && s.expiryDate.isBefore(LocalDate.now());
            return new Stage("FULFILLMENT", WAITING_HUMAN, "业务负责人", null, null,
                    overdue ? "履约中，已逾期" : "履约中，按台账跟踪", "NONE", null, false);
        }
        if (ARCHIVED_STATUS.contains(status)) {
            return new Stage("FULFILLMENT", DONE, null, null, null, "履约已结束", null, null, false);
        }
        return pending("FULFILLMENT");
    }

    private static Stage archive(Signals s) {
        if (ARCHIVED_STATUS.contains(nvl(s.caseStatus))) {
            return new Stage("ARCHIVE", DONE, null, null, null, "已归档", null, null, false);
        }
        return pending("ARCHIVE");
    }

    private static Stage pending(String key) {
        return new Stage(key, PENDING, null, null, null, null, null, null, false);
    }

    // ── 辅助 ────────────────────────────────────────────────────────

    private static Map<String, Object> first(List<Map<String, Object>> rows) {
        return rows == null || rows.isEmpty() ? null : rows.get(0);
    }

    private static String placeholders(int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < n; i++) {
            if (i > 0) sb.append(',');
            sb.append('?');
        }
        return sb.toString();
    }

    private static String str(Object v) {
        return v == null ? "" : String.valueOf(v);
    }

    private static String upper(String v) {
        return v == null ? "" : v.trim().toUpperCase(Locale.ROOT);
    }

    private static String nvl(String v) {
        return v == null ? "" : v;
    }

    private static int intOf(Object v) {
        if (v instanceof Number n) return n.intValue();
        if (v instanceof String s && !s.isBlank()) {
            try { return Integer.parseInt(s.trim()); } catch (NumberFormatException ignored) { return 0; }
        }
        return 0;
    }

    private static Long longOrNull(Object v) {
        if (v instanceof Number n) return n.longValue();
        if (v instanceof String s && !s.isBlank()) {
            try { return Long.parseLong(s.trim()); } catch (NumberFormatException ignored) { return null; }
        }
        return null;
    }

    private static LocalDateTime localDateTime(Object v) {
        if (v instanceof Timestamp ts) return ts.toLocalDateTime();
        if (v instanceof LocalDateTime ldt) return ldt;
        if (v instanceof java.util.Date d) return new Timestamp(d.getTime()).toLocalDateTime();
        return null;
    }

    private static LocalDate localDate(Object v) {
        if (v instanceof java.sql.Date d) return d.toLocalDate();
        if (v instanceof LocalDate d) return d;
        if (v instanceof Timestamp ts) return ts.toLocalDateTime().toLocalDate();
        if (v instanceof java.util.Date d) return new Timestamp(d.getTime()).toLocalDateTime().toLocalDate();
        return null;
    }

    private static String iso(LocalDateTime v) {
        return v == null ? null : v.toString();
    }

    private record Cached(Map<String, Object> result, long expiresAt) { }

    /** 推导所需的原始信号。 */
    public static final class Signals {
        String caseStatus = "";
        LocalDateTime createdAt;
        LocalDate expiryDate;
        boolean hasMainDocument;
        String parseStatus = "";
        String parseQuality = "";
        LocalDateTime mainDocumentCreatedAt;
        String snapshotStatus;
        int elementTotal;
        int elementPending;
        boolean hasExtractionRun;
        String extractionRunStatus = "";
        boolean hasTimelineRun;
        String timelineRunStatus = "";
        boolean hasReviewRun;
        String reviewRunStatus = "";
        String timelineStatus;
        int timelineTotal;
        int timelinePending;
        int openFindings;
        boolean reviewLimited;
    }

    private static final class Stage {
        final String key;
        final String state;
        final String ownerRole;
        final String enteredAt;
        final String blockedReason;
        final String summary;
        final String nextActionType;
        final String nextActionLabel;
        final boolean limited;
        final Map<String, Object> counters;

        Stage(String key, String state, String ownerRole, String enteredAt, String blockedReason,
              String summary, String nextActionType, String nextActionLabel, boolean limited) {
            this(key, state, ownerRole, enteredAt, blockedReason, summary, nextActionType, nextActionLabel,
                    limited, null);
        }

        Stage(String key, String state, String ownerRole, String enteredAt, String blockedReason,
              String summary, String nextActionType, String nextActionLabel, boolean limited,
              Map<String, Object> counters) {
            this.key = key;
            this.state = state;
            this.ownerRole = ownerRole;
            this.enteredAt = enteredAt;
            this.blockedReason = blockedReason;
            this.summary = summary;
            this.nextActionType = nextActionType;
            this.nextActionLabel = nextActionLabel;
            this.limited = limited;
            this.counters = counters;
        }
    }
}
