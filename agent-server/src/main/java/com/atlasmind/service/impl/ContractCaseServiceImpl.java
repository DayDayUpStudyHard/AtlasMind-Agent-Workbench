package com.atlasmind.service.impl;

import com.atlasmind.gateway.AiGateway;
import com.atlasmind.gateway.GitHubIssueGateway;
import com.atlasmind.service.AgentActionExecutor;
import com.atlasmind.service.ContractCaseService;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.*;

/**
 * ContractOps contract case lifecycle.
 *
 * <p>Delegates Agent run dispatch to the existing {@link AiGateway}
 * (Redis Stream + HTTP fallback).  Agent runs, reports, and actions are
 * stored in the generic {@code agent_run / agent_report / agent_action}
 * tables with {@code subject_type = 'CONTRACT_CASE'}.
 */
@Service
@RequiredArgsConstructor
public class ContractCaseServiceImpl implements ContractCaseService {

    private static final String SUBJECT_TYPE = "CONTRACT_CASE";

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final AiGateway aiGateway;
    private final GitHubIssueGateway gitHubIssueGateway;
    private final AgentActionExecutor agentActionExecutor;

    // ── Portfolio ──────────────────────────────────────────────────

    @Override
    public Map<String, Object> portfolio() {
        Map<String, Object> data = new HashMap<>();
        data.put("total", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_case WHERE deleted=0", Integer.class));
        data.put("pendingReview", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_case WHERE status IN ('READY_FOR_REVIEW','REVIEWING') AND deleted=0", Integer.class));
        data.put("pendingApproval", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_case WHERE status='PENDING_APPROVAL' AND deleted=0", Integer.class));
        data.put("inFulfillment", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_case WHERE status='IN_FULFILLMENT' AND deleted=0", Integer.class));
        data.put("expiringSoon", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_case WHERE expiry_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY) AND deleted=0", Integer.class));
        data.put("overdue", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_case WHERE status='IN_FULFILLMENT' AND expiry_date < CURDATE() AND deleted=0", Integer.class));
        // Obligation stats
        data.put("obligationsTotal", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_obligation", Integer.class));
        data.put("obligationsOverdue", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_obligation WHERE status='OVERDUE'", Integer.class));
        data.put("obligationsDueSoon", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_obligation WHERE status='PLANNED' AND due_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 7 DAY)", Integer.class));
        // Amount stats
        data.put("totalAmount", jdbcTemplate.queryForObject(
                "SELECT COALESCE(SUM(amount), 0) FROM contract_case WHERE deleted=0", java.math.BigDecimal.class));
        // Active Agent runs
        data.put("activeRuns", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM agent_run WHERE subject_type='CONTRACT_CASE' AND status IN ('CREATED','CONTEXT_BUILDING','ANALYZING','VERIFYING','PLANNING')", Integer.class));
        // Open findings
        data.put("openFindings", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_review_finding WHERE status='OPEN'", Integer.class));
        return data;
    }

    // ── List / Search ──────────────────────────────────────────────

    @Override
    public List<Map<String, Object>> listCases(Map<String, Object> filters) {
        StringBuilder sql = new StringBuilder("""
                SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                       status, counterparty, amount, currency, effective_date AS effectiveDate,
                       expiry_date AS expiryDate, department, priority, owner_id AS ownerId,
                       last_run_id AS lastRunId, last_run_at AS lastRunAt,
                       create_time AS createTime, update_time AS updateTime
                FROM contract_case WHERE deleted=0
                """);
        List<Object> params = new ArrayList<>();
        if (filters != null) {
            String status = str(filters, "status");
            if (!status.isBlank()) { sql.append(" AND status=?"); params.add(status); }
            String dept = str(filters, "department");
            if (!dept.isBlank()) { sql.append(" AND department=?"); params.add(dept); }
        }
        sql.append(" ORDER BY update_time DESC, id DESC LIMIT 50");
        return jdbcTemplate.queryForList(sql.toString(), params.toArray());
    }

    // ── Get ────────────────────────────────────────────────────────

    @Override
    public Map<String, Object> getCase(Long caseId) {
        Map<String, Object> c = first(jdbcTemplate.queryForList("""
                SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                       status, description, our_entity AS ourEntity, counterparty,
                       amount, currency, effective_date AS effectiveDate,
                       expiry_date AS expiryDate, department, owner_id AS ownerId,
                       priority, tags, approved_version_id AS approvedVersionId,
                       signed_version_id AS signedVersionId,
                       last_run_id AS lastRunId, last_run_at AS lastRunAt,
                       create_time AS createTime, update_time AS updateTime
                FROM contract_case WHERE id=? AND deleted=0
                """, caseId));
        if (c == null) throw new IllegalArgumentException("Contract case not found: " + caseId);

        c.put("parties", jdbcTemplate.queryForList(
                "SELECT id, party_name AS partyName, party_role AS partyRole, contact_person AS contactPerson, contact_email AS contactEmail, risk_score AS riskScore FROM contract_party WHERE case_id=?", caseId));
        c.put("documents", jdbcTemplate.queryForList(
                "SELECT id, document_type AS documentType, file_name AS fileName, file_size AS fileSize, version, parse_status AS parseStatus, page_count AS pageCount, create_time AS createTime FROM contract_document WHERE case_id=? ORDER BY version DESC", caseId));
        c.put("findings", jdbcTemplate.queryForList(
                "SELECT id, severity, status, title, description FROM contract_review_finding WHERE case_id=? ORDER BY severity DESC, id DESC LIMIT 20", caseId));
        c.put("obligations", jdbcTemplate.queryForList(
                "SELECT id, title, obligation_type AS obligationType, responsible_user_id AS responsibleUserId, due_date AS dueDate, status FROM contract_obligation WHERE case_id=? ORDER BY due_date ASC", caseId));
        c.put("runs", jdbcTemplate.queryForList(
                "SELECT id, run_type AS runType, status, progress, current_step AS currentStep, create_time AS createTime FROM agent_run WHERE subject_type=? AND subject_id=? ORDER BY id DESC LIMIT 10", SUBJECT_TYPE, caseId));
        c.put("reports", jdbcTemplate.queryForList(
                "SELECT id, report_type AS reportType, title, summary, status, create_time AS createTime FROM agent_report WHERE subject_type=? AND subject_id=? ORDER BY id DESC LIMIT 5", SUBJECT_TYPE, caseId));
        return c;
    }

    // ── Create ─────────────────────────────────────────────────────

    @Override
    @Transactional
    public Map<String, Object> createCase(Map<String, Object> request) {
        String title = str(request, "title");
        if (title.isBlank()) throw new IllegalArgumentException("合同标题不能为空");
        String caseKey = str(request, "caseKey");
        if (caseKey.isBlank()) caseKey = "SRV-" + System.currentTimeMillis() % 100000;

        Long id = insert("""
                INSERT INTO contract_case (case_key, title, contract_type, description,
                    our_entity, counterparty, amount, currency, effective_date, expiry_date,
                    department, owner_id, priority, tags, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'DRAFT')
                """, caseKey, title, str(request, "contractType"),
                str(request, "description"), str(request, "ourEntity"),
                str(request, "counterparty"),
                request.get("amount"), str(request, "currency"),
                request.get("effectiveDate"), request.get("expiryDate"),
                str(request, "department"), request.get("ownerId"),
                str(request, "priority"), str(request, "tags"));

        // Add counterparty party entry
        String counterparty = str(request, "counterparty");
        if (!counterparty.isBlank()) {
            jdbcTemplate.update("INSERT INTO contract_party (case_id, party_name, party_role) VALUES (?,?,'COUNTERPARTY')", id, counterparty);
        }
        String ourEntity = str(request, "ourEntity");
        if (!ourEntity.isBlank()) {
            jdbcTemplate.update("INSERT INTO contract_party (case_id, party_name, party_role) VALUES (?,?,'OUR_ENTITY')", id, ourEntity);
        }

        return getCase(id);
    }

    // ── Update ─────────────────────────────────────────────────────

    @Override
    @Transactional
    public Map<String, Object> updateCase(Long caseId, Map<String, Object> request) {
        List<String> sets = new ArrayList<>();
        List<Object> params = new ArrayList<>();
        String[] fields = {"title", "description", "counterparty", "department", "priority", "tags", "status"};
        for (String f : fields) {
            if (request.containsKey(f)) { sets.add(f + "=?"); params.add(request.get(f)); }
        }
        String[] numFields = {"amount", "ownerId"};
        for (String f : numFields) {
            if (request.containsKey(f)) { sets.add(f + "=?"); params.add(request.get(f)); }
        }
        if (sets.isEmpty()) return getCase(caseId);
        params.add(caseId);
        jdbcTemplate.update("UPDATE contract_case SET " + String.join(",", sets) + " WHERE id=?", params.toArray());
        return getCase(caseId);
    }

    // ── Documents ──────────────────────────────────────────────────

    @Override
    @Transactional
    public Map<String, Object> uploadDocument(Long caseId, Map<String, Object> request) {
        String fileName = str(request, "fileName");
        if (fileName.isBlank()) throw new IllegalArgumentException("文件名不能为空");
        jdbcTemplate.update("""
                INSERT INTO contract_document (case_id, document_type, file_name, file_path, file_size, parse_status)
                VALUES (?,?,?,?,?,'PENDING')
                """, caseId, str(request, "documentType"), fileName,
                str(request, "filePath"), request.get("fileSize"));
        return getCase(caseId);
    }

    @Override
    public List<Map<String, Object>> listDocuments(Long caseId) {
        return jdbcTemplate.queryForList(
                "SELECT id, document_type AS documentType, file_name AS fileName, file_size AS fileSize, version, parse_status AS parseStatus, create_time AS createTime FROM contract_document WHERE case_id=? ORDER BY version DESC", caseId);
    }

    // ── Agent Run delegation ───────────────────────────────────────

    @Override
    @Transactional
    public Map<String, Object> startRun(Long caseId, Map<String, Object> request) {
        Map<String, Object> c = first(jdbcTemplate.queryForList(
                "SELECT id FROM contract_case WHERE id=? AND deleted=0", caseId));
        if (c == null) throw new IllegalArgumentException("Contract case not found");

        String taskType = str(request, "taskType");
        if (taskType.isBlank()) taskType = "CONTRACT_REVIEW";

        Long runId = insert("""
                INSERT INTO agent_run (subject_type, subject_id, run_type, trigger_type, question, input_json, status, progress, current_step)
                VALUES (?,?,?,?,?,?,'CREATED',0,'等待 Agent 调度')
                """, SUBJECT_TYPE, caseId, taskType,
                str(request, "triggerType"), str(request, "question"),
                json(request.get("inputJson")));

        // Update contract_case last_run
        jdbcTemplate.update("UPDATE contract_case SET last_run_id=?, last_run_at=NOW() WHERE id=?", runId, caseId);

        dispatchAfterCommit(runId, caseId, taskType);
        return getRun(runId);
    }

    @Override
    public List<Map<String, Object>> listRuns(Long caseId) {
        return jdbcTemplate.queryForList("""
                SELECT id, run_type AS runType, status, progress, current_step AS currentStep,
                       error_message AS errorMessage, create_time AS createTime
                FROM agent_run WHERE subject_type=? AND subject_id=? ORDER BY id DESC LIMIT 20
                """, SUBJECT_TYPE, caseId);
    }

    @Override
    public Map<String, Object> getRun(Long runId) {
        Map<String, Object> run = first(jdbcTemplate.queryForList("""
                SELECT id, subject_type AS subjectType, subject_id AS subjectId, run_type AS runType,
                       status, progress, current_step AS currentStep, error_message AS errorMessage,
                       create_time AS createTime
                FROM agent_run WHERE id=?
                """, runId));
        if (run == null) throw new IllegalArgumentException("Run not found");
        return run;
    }

    @Override
    @Transactional
    public Map<String, Object> approveAction(Long runId, Long actionId, Map<String, Object> request, String approvedBy) {
        Map<String, Object> action = first(jdbcTemplate.queryForList(
                "SELECT id FROM agent_action WHERE id=? AND run_id=?", actionId, runId));
        if (action == null) throw new IllegalArgumentException("Action not found");

        boolean approved = request.get("approved") == null || Boolean.TRUE.equals(request.get("approved"));
        String approver = approvedBy == null || approvedBy.isBlank() ? "authenticated-user" : approvedBy;
        jdbcTemplate.update("""
                UPDATE agent_action SET status=?, approved_by=?, approved_at=NOW()
                WHERE id=? AND run_id=?
                """, approved ? "APPROVED" : "REJECTED", approver, actionId, runId);

        if (approved) {
            dispatchActionAfterCommit(runId, actionId);
        }
        return getRun(runId);
    }

    @Override
    @Transactional
    public Map<String, Object> executeAction(Long runId, Long actionId) {
        // Mirror of AgentProjectServiceImpl.executeAction() for contract actions
        Map<String, Object> action = first(jdbcTemplate.queryForList("""
                SELECT a.id, a.subject_id AS subjectId, a.action_type AS actionType,
                       a.status, a.title, a.payload_json AS payloadJson
                FROM agent_action a WHERE a.id=? AND a.run_id=?
                """, actionId, runId));
        if (action == null) throw new IllegalArgumentException("Action not found");
        if (!"APPROVED".equals(action.get("status")))
            throw new IllegalArgumentException("Action must be APPROVED before execution");

        String actionType = str(action, "actionType");
        try {
            Map<String, Object> result;
            String completedStep;
            switch (actionType) {
                case "CREATE_NEGOTIATION_TASK" -> {
                    result = Map.of("created", true);
                    completedStep = "协商任务已创建";
                }
                case "SCHEDULE_REMINDER" -> {
                    result = Map.of("scheduled", true);
                    completedStep = "提醒已排期";
                }
                default -> {
                    result = Map.of("executed", true);
                    completedStep = "动作已执行";
                }
            }
            jdbcTemplate.update("""
                    UPDATE agent_action SET status='EXECUTED', executed_at=NOW(), result_json=?
                    WHERE id=? AND run_id=?
                    """, json(result), actionId, runId);
            jdbcTemplate.update("UPDATE agent_run SET status='COMPLETED', progress=100, current_step=? WHERE id=?", completedStep, runId);
        } catch (Exception e) {
            jdbcTemplate.update("UPDATE agent_action SET status='BLOCKED', error_message=? WHERE id=? AND run_id=?", e.getMessage(), actionId);
        }
        return getRun(runId);
    }

    // ── Dispatch helpers ───────────────────────────────────────────

    private void dispatchAfterCommit(Long runId, Long caseId, String taskType) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            dispatchToPython(runId, caseId, taskType);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() { dispatchToPython(runId, caseId, taskType); }
        });
    }

    private void dispatchToPython(Long runId, Long caseId, String taskType) {
        try {
            Map<String, Object> c = first(jdbcTemplate.queryForList(
                    "SELECT id, case_key AS caseKey, title, contract_type AS contractType FROM contract_case WHERE id=?", caseId));
            Map<String, Object> payload = new HashMap<>();
            payload.put("requestId", UUID.randomUUID().toString());
            payload.put("subjectType", SUBJECT_TYPE);
            payload.put("subjectId", caseId);
            payload.put("runId", runId);
            payload.put("taskType", taskType);
            payload.put("goal", "Contract case " + (c != null ? str(c, "caseKey") : "#" + caseId));
            payload.put("project", c != null ? c : Map.of());
            payload.put("question", "");
            payload.put("actor", "java-service");
            payload.put("taskInput", Map.of());
            payload.put("options", Map.of());
            aiGateway.startAgentRun(payload);
        } catch (Exception e) {
            jdbcTemplate.update("UPDATE agent_run SET status='FAILED', progress=0, current_step='Agent 服务不可用', error_message=? WHERE id=?", e.getMessage(), runId);
        }
    }

    private void dispatchActionAfterCommit(Long runId, Long actionId) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            agentActionExecutor.execute(runId, actionId);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() { agentActionExecutor.execute(runId, actionId); }
        });
    }

    // ── Obligations (Phase 8) ─────────────────────────────────────

    @Override
    public List<Map<String, Object>> listObligations(Long caseId) {
        return jdbcTemplate.queryForList(
                "SELECT id, title, obligation_type AS obligationType, responsible_user_id AS responsibleUserId,"
                + " due_date AS dueDate, trigger_condition AS triggerCondition, status,"
                + " evidence_required AS evidenceRequired, completed_at AS completedAt"
                + " FROM contract_obligation WHERE case_id=? ORDER BY due_date ASC", caseId);
    }

    @Override
    @Transactional
    public Map<String, Object> createObligation(Long caseId, Map<String, Object> request) {
        jdbcTemplate.update("""
                INSERT INTO contract_obligation (case_id, title, obligation_type, responsible_user_id, due_date, trigger_condition, evidence_required, status)
                VALUES (?,?,?,?,?,?,?,'PLANNED')
                """, caseId, str(request, "title"), str(request, "obligationType"),
                request.get("responsibleUserId"), request.get("dueDate"),
                str(request, "triggerCondition"), request.getOrDefault("evidenceRequired", 0));
        return getCase(caseId);
    }

    @Override
    @Transactional
    public Map<String, Object> updateObligation(Long obligationId, Map<String, Object> request) {
        List<String> sets = new ArrayList<>();
        List<Object> params = new ArrayList<>();
        for (String f : new String[]{"status", "title"}) {
            if (request.containsKey(f)) { sets.add(f + "=?"); params.add(request.get(f)); }
        }
        if (request.containsKey("completedAt")) {
            sets.add("completed_at=?,completed_by=?"); params.add(request.get("completedAt")); params.add(request.get("completedBy"));
        }
        if (!sets.isEmpty()) {
            params.add(obligationId);
            jdbcTemplate.update("UPDATE contract_obligation SET " + String.join(",", sets) + " WHERE id=?", params.toArray());
        }
        return Map.of("id", obligationId, "updated", true);
    }

    @Override
    @Transactional
    public Map<String, Object> uploadFulfillmentEvidence(Long caseId, Map<String, Object> request) {
        jdbcTemplate.update("""
                INSERT INTO contract_document (case_id, document_type, file_name, file_path, file_size, parse_status)
                VALUES (?,'FULFILLMENT_EVIDENCE',?,?,?,'PENDING')
                """, caseId, str(request, "fileName"), str(request, "filePath"), request.get("fileSize"));
        return getCase(caseId);
    }

    @Override
    public List<Map<String, Object>> listReminders() {
        return jdbcTemplate.queryForList("""
                SELECT o.id, o.title, o.due_date AS dueDate, o.status, c.case_key AS caseKey, c.title AS caseTitle
                FROM contract_obligation o JOIN contract_case c ON c.id=o.case_id
                WHERE o.status IN ('PLANNED','OVERDUE','DUE_SOON')
                ORDER BY o.due_date ASC LIMIT 30
                """);
    }

    // ── DB helpers ─────────────────────────────────────────────────

    private Long insert(String sql, Object... params) {
        var keyHolder = (org.springframework.jdbc.support.KeyHolder) new org.springframework.jdbc.support.GeneratedKeyHolder();
        jdbcTemplate.update(con -> {
            var ps = con.prepareStatement(sql, Statement.RETURN_GENERATED_KEYS);
            for (int i = 0; i < params.length; i++) ps.setObject(i + 1, params[i]);
            return ps;
        }, keyHolder);
        Number key = keyHolder.getKey();
        return key != null ? key.longValue() : null;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> first(List<Map<String, Object>> rows) {
        return rows.isEmpty() ? null : rows.get(0);
    }

    private String str(Map<String, Object> m, String k) {
        Object v = m == null ? null : m.get(k);
        return v == null ? "" : String.valueOf(v);
    }

    private String json(Object value) {
        try { return value == null ? "{}" : objectMapper.writeValueAsString(value); }
        catch (Exception e) { return "{}"; }
    }
}
