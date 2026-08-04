package com.atlasmind.controller;

import com.atlasmind.common.Result;
import com.atlasmind.gateway.AiGateway;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/contracts")
public class ContractAdminController {

    private final JdbcTemplate jdbc;
    private final AiGateway aiGateway;

    // ── Contract case management ──────────────────────────────────

    @GetMapping("/cases")
    public Result<Map<String, Object>> listCases(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "false") boolean deleted) {
        long safePage = Math.max(1, page);
        long safeSize = Math.max(1, Math.min(size, 100));
        long offset = (safePage - 1) * safeSize;
        String keywordFilter = keyword == null || keyword.isBlank() ? null : keyword.trim();
        String statusFilter = status == null || status.isBlank() ? null : status.trim().toUpperCase();

        String baseWhere = """
                WHERE c.deleted=?
                  AND (? IS NULL OR c.status=?)
                  AND (? IS NULL OR c.case_key LIKE CONCAT('%', ?, '%')
                       OR c.title LIKE CONCAT('%', ?, '%')
                       OR c.counterparty LIKE CONCAT('%', ?, '%'))
                """;
        List<Map<String, Object>> records = jdbc.queryForList("""
                SELECT c.id, c.case_key AS caseKey, c.title, c.counterparty,
                       c.contract_type AS contractType, c.status, c.amount, c.currency,
                       c.department, c.priority, c.create_time AS createTime,
                       c.update_time AS updateTime,
                       (SELECT COUNT(*) FROM contract_document d WHERE d.case_id=c.id) AS documentCount,
                       (SELECT COUNT(*) FROM agent_run r WHERE r.subject_type='CONTRACT_CASE' AND r.subject_id=c.id) AS runCount,
                       (SELECT COUNT(*) FROM agent_report rp WHERE rp.subject_type='CONTRACT_CASE' AND rp.subject_id=c.id) AS reportCount,
                       (SELECT COUNT(*) FROM contract_timeline_node n WHERE n.case_id=c.id) AS timelineNodeCount,
                       (SELECT COUNT(*) FROM contract_review_finding f WHERE f.case_id=c.id AND f.status='OPEN') AS openFindingCount
                FROM contract_case c
                """ + baseWhere + """
                ORDER BY c.update_time DESC, c.id DESC
                LIMIT ?, ?
                """,
                deleted ? 1 : 0,
                statusFilter, statusFilter,
                keywordFilter, keywordFilter, keywordFilter, keywordFilter,
                offset, safeSize);
        Long total = jdbc.queryForObject("""
                SELECT COUNT(*)
                FROM contract_case c
                """ + baseWhere,
                Long.class,
                deleted ? 1 : 0,
                statusFilter, statusFilter,
                keywordFilter, keywordFilter, keywordFilter, keywordFilter);
        Map<String, Object> data = new HashMap<>();
        data.put("records", records);
        data.put("total", total == null ? 0 : total);
        return Result.ok(data);
    }

    @GetMapping("/cases/{id}/delete-impact")
    public Result<Map<String, Object>> deleteImpact(@PathVariable Long id) {
        return Result.ok(caseDeleteImpact(id));
    }

    @DeleteMapping("/cases/{id}")
    @Transactional
    public Result<Map<String, Object>> softDeleteCase(@PathVariable Long id) {
        Map<String, Object> impact = caseDeleteImpact(id);
        int updated = jdbc.update("UPDATE contract_case SET deleted=1 WHERE id=? AND deleted=0", id);
        if (updated == 0) throw new IllegalArgumentException("合同案件不存在或已删除");
        impact.put("deleted", true);
        return Result.ok(impact);
    }

    @PostMapping("/cases/{id}/restore")
    public Result<Map<String, Object>> restoreCase(@PathVariable Long id) {
        int updated = jdbc.update("UPDATE contract_case SET deleted=0 WHERE id=? AND deleted=1", id);
        if (updated == 0) throw new IllegalArgumentException("合同案件不存在或未删除");
        return Result.ok(Map.of("restored", true, "caseId", id));
    }

    private Map<String, Object> caseDeleteImpact(Long id) {
        List<Map<String, Object>> cases = jdbc.queryForList("""
                SELECT id AS caseId, case_key AS caseKey, title, status, deleted
                FROM contract_case
                WHERE id=?
                """, id);
        if (cases.isEmpty()) {
            throw new IllegalArgumentException("合同案件不存在");
        }
        Map<String, Object> impact = new HashMap<>(cases.get(0));
        impact.put("documentCount", countCaseRefs("SELECT COUNT(*) FROM contract_document WHERE case_id=?", id));
        impact.put("clauseCount", countCaseRefs("SELECT COUNT(*) FROM contract_clause WHERE case_id=?", id));
        impact.put("chunkCount", countCaseRefs("SELECT COUNT(*) FROM contract_clause_chunk WHERE case_id=?", id));
        impact.put("timelineNodeCount", countCaseRefs("SELECT COUNT(*) FROM contract_timeline_node WHERE case_id=?", id));
        impact.put("runCount", countCaseRefs("""
                SELECT COUNT(*) FROM agent_run
                WHERE subject_type='CONTRACT_CASE' AND subject_id=?
                """, id));
        impact.put("reportCount", countCaseRefs("""
                SELECT COUNT(*) FROM agent_report
                WHERE subject_type='CONTRACT_CASE' AND subject_id=?
                """, id));
        impact.put("actionCount", countCaseRefs("""
                SELECT COUNT(*)
                FROM agent_action a
                JOIN agent_run r ON r.id=a.run_id
                WHERE r.subject_type='CONTRACT_CASE' AND r.subject_id=?
                """, id));
        impact.put("openFindingCount", countCaseRefs("""
                SELECT COUNT(*) FROM contract_review_finding
                WHERE case_id=? AND status='OPEN'
                """, id));
        return impact;
    }

    private long countCaseRefs(String sql, Long id) {
        Long count = jdbc.queryForObject(sql, Long.class, id);
        return count == null ? 0 : count;
    }

    // ── Review Rules ──────────────────────────────────────────────

    @GetMapping("/rules")
    public Result<List<Map<String, Object>>> listRules() {
        return Result.ok(jdbc.queryForList(
            "SELECT id, rule_key AS ruleKey, rule_set AS ruleSet, clause_type AS clauseType, title, description, check_type AS checkType, check_config AS checkConfig, severity, weight, is_veto AS isVeto, is_active AS isActive, version, create_time AS createTime FROM contract_review_rule ORDER BY rule_set, clause_type, id"));
    }

    @PostMapping("/rules")
    public Result<Map<String, Object>> createRule(@RequestBody Map<String, Object> r) {
        jdbc.update("INSERT INTO contract_review_rule (rule_key, rule_set, clause_type, title, description, check_type, check_config, severity, weight, is_veto, is_active, version)"
            + " VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
            r.get("ruleKey"), r.get("ruleSet"), r.get("clauseType"), r.get("title"), r.get("description"),
            r.getOrDefault("checkType", "MISSING"), r.get("checkConfig"), r.getOrDefault("severity", "MEDIUM"),
            r.getOrDefault("weight", 10), r.getOrDefault("isVeto", 0), r.getOrDefault("isActive", 1));
        return Result.ok(Map.of("created", true));
    }

    @PutMapping("/rules/{id}")
    public Result<Map<String, Object>> updateRule(@PathVariable Long id, @RequestBody Map<String, Object> r) {
        java.util.List<String> sets = new java.util.ArrayList<>();
        java.util.List<Object> params = new java.util.ArrayList<>();
        Map<String, String> columns = Map.of(
            "title", "title", "description", "description", "severity", "severity",
            "weight", "weight", "checkType", "check_type", "checkConfig", "check_config");
        for (Map.Entry<String, String> field : columns.entrySet()) {
            if (r.containsKey(field.getKey())) {
                sets.add(field.getValue() + "=?");
                params.add(r.get(field.getKey()));
            }
        }
        if (r.containsKey("isActive")) { sets.add("is_active=?"); params.add(r.get("isActive")); }
        if (r.containsKey("isVeto")) { sets.add("is_veto=?"); params.add(r.get("isVeto")); }
        if (sets.isEmpty()) return Result.ok(Map.of("updated", false));
        params.add(id);
        int updated = jdbc.update("UPDATE contract_review_rule SET " + String.join(",", sets) + " WHERE id=?", params.toArray());
        return Result.ok(Map.of("updated", updated > 0));
    }

    @DeleteMapping("/rules/{id}")
    public Result<Map<String, Object>> deleteRule(@PathVariable Long id) {
        jdbc.update("DELETE FROM contract_review_rule WHERE id=?", id);
        return Result.ok(Map.of("deleted", true));
    }

    // ── Standard Clauses ──────────────────────────────────────────

    @GetMapping("/clauses")
    public Result<List<Map<String, Object>>> listClauses() {
        return Result.ok(jdbc.queryForList(
            "SELECT id, clause_type AS clauseType, title, content, semantic_elements AS semanticElements, is_mandatory AS isMandatory, negotiation_bottom_line AS negotiationBottomLine, version, is_active AS isActive, effective_from AS effectiveFrom, effective_to AS effectiveTo, create_time AS createTime FROM contract_standard_clause ORDER BY clause_type, id"));
    }

    @PostMapping("/clauses")
    public Result<Map<String, Object>> createClause(@RequestBody Map<String, Object> r) {
        jdbc.update("INSERT INTO contract_standard_clause (clause_type, title, content, semantic_elements, is_mandatory, negotiation_bottom_line, is_active, version)"
            + " VALUES (?,?,?,?,?,?,?,1)",
            r.get("clauseType"), r.get("title"), r.get("content"), r.get("semanticElements"),
            r.getOrDefault("isMandatory", 0), r.get("negotiationBottomLine"), r.getOrDefault("isActive", 1));
        return Result.ok(Map.of("created", true));
    }

    @PutMapping("/clauses/{id}")
    public Result<Map<String, Object>> updateClause(@PathVariable Long id, @RequestBody Map<String, Object> r) {
        java.util.List<String> sets = new java.util.ArrayList<>();
        java.util.List<Object> params = new java.util.ArrayList<>();
        Map<String, String> columns = Map.of(
            "title", "title", "content", "content",
            "semanticElements", "semantic_elements",
            "negotiationBottomLine", "negotiation_bottom_line");
        for (Map.Entry<String, String> field : columns.entrySet()) {
            if (r.containsKey(field.getKey())) {
                sets.add(field.getValue() + "=?");
                params.add(r.get(field.getKey()));
            }
        }
        if (r.containsKey("isActive")) { sets.add("is_active=?"); params.add(r.get("isActive")); }
        if (r.containsKey("isMandatory")) { sets.add("is_mandatory=?"); params.add(r.get("isMandatory")); }
        if (sets.isEmpty()) return Result.ok(Map.of("updated", false));
        params.add(id);
        int updated = jdbc.update(
            "UPDATE contract_standard_clause SET " + String.join(",", sets) + " WHERE id=?",
            params.toArray());
        return Result.ok(Map.of("updated", updated > 0));
    }

    @DeleteMapping("/clauses/{id}")
    public Result<Map<String, Object>> deleteClause(@PathVariable Long id) {
        jdbc.update("DELETE FROM contract_standard_clause WHERE id=?", id);
        return Result.ok(Map.of("deleted", true));
    }

    // ── Document management (admin) ─────────────────────────────────

    /** List all contract documents across all cases (admin view). */
    @GetMapping("/documents")
    public Result<List<Map<String, Object>>> listAllDocuments() {
        return Result.ok(jdbc.queryForList(
            "SELECT d.id, d.case_id AS caseId, c.case_key AS caseKey, c.title AS caseTitle,"
            + " d.document_type AS documentType, d.file_name AS fileName, d.file_size AS fileSize,"
            + " d.version, d.parse_status AS parseStatus, d.parse_error AS parseError,"
            + " d.page_count AS pageCount, d.content_text IS NOT NULL AS hasInlineText,"
            + " CHAR_LENGTH(d.content_text) AS textLength, d.create_time AS createTime"
            + " FROM contract_document d JOIN contract_case c ON c.id=d.case_id"
            + " WHERE c.deleted=0 ORDER BY d.create_time DESC LIMIT 100"));
    }

    /** Cancel a document parse job — set status to FAILED. */
    @PutMapping("/documents/{id}/cancel")
    public Result<Map<String, Object>> cancelDocument(@PathVariable Long id) {
        int updated = jdbc.update(
            "UPDATE contract_document SET parse_status='FAILED', parse_error='用户手动停止' WHERE id=? AND parse_status IN ('PENDING','PARSING')", id);
        return Result.ok(Map.of("cancelled", updated > 0));
    }

    /** Delete a contract document. */
    @DeleteMapping("/documents/{id}")
    @Transactional
    public Result<Map<String, Object>> deleteDocument(@PathVariable Long id) {
        List<Map<String, Object>> documents = jdbc.queryForList(
            "SELECT id, case_id AS caseId FROM contract_document WHERE id=?", id);
        if (documents.isEmpty()) {
            throw new IllegalArgumentException("合同文件不存在");
        }
        Long caseId = ((Number) documents.get(0).get("caseId")).longValue();
        jdbc.update("UPDATE contract_case SET approved_version_id=NULL WHERE id=? AND approved_version_id=?", caseId, id);
        jdbc.update("UPDATE contract_case SET signed_version_id=NULL WHERE id=? AND signed_version_id=?", caseId, id);
        int deletedClauses = jdbc.update("DELETE FROM contract_clause WHERE document_id=?", id);
        jdbc.update("DELETE FROM contract_document WHERE id=?", id);
        return Result.ok(Map.of("deleted", true, "deletedClauses", deletedClauses));
    }

    /** Retry parsing for a PENDING or FAILED document. */
    @PostMapping("/documents/{id}/retry-parse")
    @Transactional
    public Result<Map<String, Object>> retryDocumentParse(@PathVariable Long id) {
        jdbc.update("UPDATE contract_document SET parse_status='PENDING', parse_error=NULL WHERE id=?", id);
        jdbc.update("UPDATE contract_intake SET status='PENDING', error_message=NULL WHERE case_id=(SELECT case_id FROM contract_document WHERE id=?) AND status='FAILED'", id);
        // Dispatch to Python worker
        try {
            aiGateway.parseContractDocument(id);
        } catch (Exception e) {
            return Result.ok(Map.of("retried", true, "dispatchWarning", "解析任务已排队，但 AI 服务暂不可达: " + e.getMessage()));
        }
        return Result.ok(Map.of("retried", true));
    }

    // ── Reports and actions (contract domain) ──────────────────────

    @GetMapping("/reports")
    public Result<List<Map<String, Object>>> listReports() {
        return Result.ok(jdbc.queryForList("""
            SELECT rp.id, rp.run_id AS runId, r.subject_type AS subjectType,
                   r.subject_id AS subjectId, c.title AS caseTitle,
                   rp.report_type AS reportType, rp.title, rp.summary,
                   rp.health_status AS healthStatus, rp.health_score AS healthScore,
                   rp.status, rp.create_time AS createTime
            FROM agent_report rp
            JOIN agent_run r ON r.id=rp.run_id AND r.subject_type='CONTRACT_CASE'
            LEFT JOIN contract_case c ON c.id=r.subject_id AND c.deleted=0
            ORDER BY rp.id DESC LIMIT 100
            """));
    }

    @DeleteMapping("/reports/{id}")
    public Result<Map<String, Object>> deleteReport(@PathVariable Long id) {
        int deleted = jdbc.update("""
            DELETE rp FROM agent_report rp
            JOIN agent_run r ON r.id=rp.run_id AND r.subject_type='CONTRACT_CASE'
            WHERE rp.id=?
            """, id);
        if (deleted == 0) throw new IllegalArgumentException("合同报告不存在");
        return Result.ok(Map.of("deleted", true, "reportId", id));
    }

    @GetMapping("/actions")
    public Result<List<Map<String, Object>>> listActions(
            @RequestParam(required = false) String status) {
        String statusFilter = status == null || status.isBlank() ? null : status.trim().toUpperCase();
        return Result.ok(jdbc.queryForList("""
            SELECT a.id, a.run_id AS runId, r.subject_type AS subjectType,
                   r.subject_id AS subjectId, c.title AS caseTitle,
                   a.action_type AS actionType, a.status, a.title,
                   a.external_id AS externalId, a.error_message AS errorMessage,
                   a.create_time AS createTime
            FROM agent_action a
            JOIN agent_run r ON r.id=a.run_id AND r.subject_type='CONTRACT_CASE'
            LEFT JOIN contract_case c ON c.id=r.subject_id AND c.deleted=0
            WHERE (? IS NULL OR a.status=?)
            ORDER BY a.id DESC LIMIT 100
            """, statusFilter, statusFilter));
    }

    @DeleteMapping("/actions/{id}")
    @Transactional
    public Result<Map<String, Object>> deleteAction(@PathVariable Long id) {
        List<Map<String, Object>> actions = jdbc.queryForList("""
            SELECT a.id, a.status FROM agent_action a
            JOIN agent_run r ON r.id=a.run_id AND r.subject_type='CONTRACT_CASE'
            WHERE a.id=? FOR UPDATE
            """, id);
        if (actions.isEmpty()) throw new IllegalArgumentException("合同动作不存在");
        if ("APPROVED".equals(actions.get(0).get("status"))) {
            throw new IllegalArgumentException("已批准且可能正在执行的动作不能删除");
        }
        jdbc.update("DELETE FROM agent_action WHERE id=?", id);
        return Result.ok(Map.of("deleted", true, "actionId", id));
    }

    // ── Agent Run management (admin) ─────────────────────────────────

    /** Force-stop a running Agent run. Sets status to CANCELLED so the
     *  Python harness picks up the cancellation at its next check point. */
    @PutMapping("/runs/{id}/cancel")
    public Result<Map<String, Object>> cancelRun(@PathVariable Long id) {
        int updated = jdbc.update(
            "UPDATE agent_run SET status='CANCELLED', progress=0, current_step='管理员手动停止' WHERE id=? AND subject_type='CONTRACT_CASE' AND status IN ('CREATED','CONTEXT_BUILDING','PLANNING','ANALYZING','VERIFYING')", id);
        return Result.ok(Map.of("cancelled", updated > 0, "runId", id));
    }

    /** Delete an Agent run and its associated traces, tool calls, and report. */
    @DeleteMapping("/runs/{id}")
    @Transactional
    public Result<Map<String, Object>> deleteRun(@PathVariable Long id) {
        List<Map<String, Object>> runs = jdbc.queryForList(
            "SELECT id FROM agent_run WHERE id=? AND subject_type='CONTRACT_CASE' FOR UPDATE", id);
        if (runs.isEmpty()) throw new IllegalArgumentException("合同 Agent Run 不存在");
        // Cancel first if still running
        jdbc.update("UPDATE agent_run SET status='CANCELLED' WHERE id=? AND status IN ('CREATED','CONTEXT_BUILDING','PLANNING','ANALYZING','VERIFYING')", id);
        jdbc.update("DELETE FROM agent_run_trace WHERE run_id=?", id);
        jdbc.update("DELETE FROM agent_tool_call WHERE run_id=?", id);
        jdbc.update("DELETE FROM agent_report WHERE run_id=?", id);
        jdbc.update("DELETE FROM agent_action WHERE run_id=?", id);
        jdbc.update("DELETE FROM agent_run WHERE id=?", id);
        return Result.ok(Map.of("deleted", true, "runId", id));
    }
}
