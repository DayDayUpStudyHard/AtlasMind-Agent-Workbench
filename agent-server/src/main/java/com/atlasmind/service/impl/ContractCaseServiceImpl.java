package com.atlasmind.service.impl;

import com.atlasmind.gateway.AiGateway;
import com.atlasmind.gateway.GitHubIssueGateway;
import com.atlasmind.service.AgentActionExecutor;
import com.atlasmind.service.ContractCaseService;
import com.atlasmind.service.KnowledgeBaseService;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.PreparedStatement;
import java.sql.Statement;
import java.time.LocalDate;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

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
    private static final int MAX_INLINE_CONTRACT_CHARS = 2_000_000;
    private static final Set<String> DOCUMENT_TYPES = Set.of(
            "MAIN", "ATTACHMENT", "PRICING", "CERTIFICATE",
            "FULFILLMENT_EVIDENCE", "OTHER");
    private static final Set<String> CONTRACT_TYPES = Set.of(
            "SERVICE_PROCUREMENT", "GOODS_PURCHASE", "NDA", "OTHER");
    private static final Set<String> PRIORITIES = Set.of("LOW", "NORMAL", "HIGH", "CRITICAL");
    private static final Pattern ABSOLUTE_DATE_PATTERN = Pattern.compile(
            "(20\\d{2})\\s*[-年./]\\s*(0?[1-9]|1[0-2])\\s*[-月./]\\s*(0?[1-9]|[12]\\d|3[01])\\s*日?");
    private static final Pattern MONTH_DAY_PATTERN = Pattern.compile(
            "(?<!\\d)(0?[1-9]|1[0-2])月(0?[1-9]|[12]\\d|3[01])日");
    private static final Pattern RELATIVE_TERM_PATTERN = Pattern.compile(
            "(合同签署之日|合同生效|生效日|服务期满|合同到期|验收通过|收到发票|交付完成|付款通知|书面通知)(前|后|起)?\\s*(\\d{1,3})\\s*(个)?\\s*(工作日|自然日|日|天|月|年)(内|前|后)?");
    private static final Pattern DURATION_TERM_PATTERN = Pattern.compile(
            "(提前|逾期|超过|不少于|不晚于|不迟于|每|自|在|期满|续签|终止|验收|付款|交付|通知)?[^，。；;\\n]{0,20}?(\\d{1,3})\\s*(个)?\\s*(工作日|自然日|日|天|月|年)(内|前|后|起|届满|期)?");
    private static final Pattern CHINESE_DURATION_TERM_PATTERN = Pattern.compile(
            "(提前|逾期|超过|不少于|不晚于|不迟于|每|自|在|期满|续签|终止|验收|付款|交付|通知)?[^，。；;\\n]{0,20}?([一二两三四五六七八九十]+)\\s*(个)?\\s*(工作日|自然日|日|天|月|年)(内|前|后|起|届满|期)?");

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final AiGateway aiGateway;
    private final GitHubIssueGateway gitHubIssueGateway;
    private final AgentActionExecutor agentActionExecutor;
    private final KnowledgeBaseService knowledgeBaseService;

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
        data.put("workQueues", workQueueSummary());
        return data;
    }

    @Override
    public Map<String, Object> workQueueSummary() {
        Map<String, Object> data = new HashMap<>();
        data.put("review", jdbcTemplate.queryForObject("""
                SELECT
                    (SELECT COUNT(*) FROM contract_case
                     WHERE status IN ('READY_FOR_REVIEW','REVIEWING') AND deleted=0)
                    +
                    (SELECT COUNT(*) FROM contract_document d
                     JOIN contract_case c ON c.id=d.case_id AND c.deleted=0
                     WHERE d.parse_status IN ('PENDING','PARSING','FAILED'))
                """, Integer.class));
        data.put("approval", jdbcTemplate.queryForObject("""
                SELECT
                    (SELECT COUNT(*) FROM contract_review_finding WHERE status='OPEN')
                    +
                    (SELECT COUNT(*) FROM agent_action
                     WHERE subject_type=? AND status='PENDING_APPROVAL')
                    +
                    (SELECT COUNT(*) FROM agent_report
                     WHERE subject_type=? AND report_type IN ('CONTRACT_REVIEW_REPORT','APPROVAL_MEMO')
                       AND status='DRAFT')
                """, Integer.class, SUBJECT_TYPE, SUBJECT_TYPE));
        data.put("fulfillment", jdbcTemplate.queryForObject("""
                SELECT
                    (SELECT COUNT(*) FROM contract_obligation
                     WHERE status IN ('OVERDUE','DUE_SOON')
                        OR (status='PLANNED' AND due_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 7 DAY)))
                    +
                    (SELECT COUNT(*) FROM contract_case
                     WHERE deleted=0 AND expiry_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY))
                    +
                    (SELECT COUNT(*) FROM contract_case c
                     WHERE c.deleted=0 AND c.status='SIGNED'
                       AND NOT EXISTS (SELECT 1 FROM contract_obligation o WHERE o.case_id=c.id))
                """, Integer.class));
        return data;
    }

    @Override
    public List<Map<String, Object>> listWorkQueue(String type) {
        String queueType = type == null ? "REVIEW" : type.trim().toUpperCase(Locale.ROOT);
        return switch (queueType) {
            case "APPROVAL" -> jdbcTemplate.queryForList("""
                    SELECT 'OPEN_FINDING' AS itemType, f.id AS itemId, c.id AS caseId,
                           c.case_key AS caseKey, c.title AS caseTitle, f.title,
                           f.severity AS severity, f.status, f.create_time AS createTime
                    FROM contract_review_finding f
                    JOIN contract_case c ON c.id=f.case_id AND c.deleted=0
                    WHERE f.status='OPEN'
                    UNION ALL
                    SELECT 'PENDING_ACTION' AS itemType, a.id AS itemId, c.id AS caseId,
                           c.case_key AS caseKey, c.title AS caseTitle, a.title,
                           NULL AS severity, a.status, a.create_time AS createTime
                    FROM agent_action a
                    JOIN contract_case c ON c.id=a.subject_id AND c.deleted=0
                    WHERE a.subject_type=? AND a.status='PENDING_APPROVAL'
                    ORDER BY createTime DESC LIMIT 12
                    """, SUBJECT_TYPE);
            case "FULFILLMENT" -> jdbcTemplate.queryForList("""
                    SELECT 'OBLIGATION' AS itemType, o.id AS itemId, c.id AS caseId,
                           c.case_key AS caseKey, c.title AS caseTitle, o.title,
                           o.status, o.due_date AS dueDate, o.create_time AS createTime
                    FROM contract_obligation o
                    JOIN contract_case c ON c.id=o.case_id AND c.deleted=0
                    WHERE o.status IN ('OVERDUE','DUE_SOON')
                       OR (o.status='PLANNED' AND o.due_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 7 DAY))
                    UNION ALL
                    SELECT 'EXPIRING_CONTRACT' AS itemType, c.id AS itemId, c.id AS caseId,
                           c.case_key AS caseKey, c.title AS caseTitle, '合同即将到期' AS title,
                           c.status, c.expiry_date AS dueDate, c.update_time AS createTime
                    FROM contract_case c
                    WHERE c.deleted=0 AND c.expiry_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
                    UNION ALL
                    SELECT 'MISSING_OBLIGATIONS' AS itemType, c.id AS itemId, c.id AS caseId,
                           c.case_key AS caseKey, c.title AS caseTitle, '待提取履约义务' AS title,
                           c.status, c.expiry_date AS dueDate, c.update_time AS createTime
                    FROM contract_case c
                    WHERE c.deleted=0 AND c.status='SIGNED'
                      AND NOT EXISTS (SELECT 1 FROM contract_obligation o WHERE o.case_id=c.id)
                    ORDER BY dueDate ASC, createTime DESC LIMIT 12
                    """);
            default -> jdbcTemplate.queryForList("""
                    SELECT 'DOCUMENT_PARSE' AS itemType, d.id AS itemId, c.id AS caseId,
                           c.case_key AS caseKey, c.title AS caseTitle,
                           CONCAT(d.file_name, '：', d.parse_status) AS title,
                           d.parse_status AS status, d.create_time AS createTime
                    FROM contract_document d
                    JOIN contract_case c ON c.id=d.case_id AND c.deleted=0
                    WHERE d.parse_status IN ('PENDING','PARSING','FAILED')
                    UNION ALL
                    SELECT 'READY_REVIEW' AS itemType, c.id AS itemId, c.id AS caseId,
                           c.case_key AS caseKey, c.title AS caseTitle,
                           '等待合同审查' AS title, c.status, c.update_time AS createTime
                    FROM contract_case c
                    WHERE c.deleted=0 AND c.status IN ('READY_FOR_REVIEW','REVIEWING')
                    ORDER BY createTime DESC LIMIT 12
                    """);
        };
    }

    // ── List / Search ──────────────────────────────────────────────

    @Override
    public List<Map<String, Object>> listCases(Map<String, Object> filters) {
        StringBuilder sql = new StringBuilder("""
                SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                       status, our_entity AS ourEntity, counterparty, our_side AS ourSide,
                       amount, currency, effective_date AS effectiveDate,
                       expiry_date AS expiryDate, signed_date AS signedDate,
                       department, priority, owner_id AS ownerId,
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
        List<Map<String, Object>> rows = jdbcTemplate.queryForList(sql.toString(), params.toArray());
        attachTimelineNodes(rows);
        return rows;
    }

    // ── Get ────────────────────────────────────────────────────────

    @Override
    public Map<String, Object> getCase(Long caseId) {
        Map<String, Object> c = first(jdbcTemplate.queryForList("""
                SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                       status, description, our_entity AS ourEntity, counterparty,
                       our_side AS ourSide,
                       amount, currency, effective_date AS effectiveDate,
                       expiry_date AS expiryDate, signed_date AS signedDate,
                       department, owner_id AS ownerId,
                       priority, tags, approved_version_id AS approvedVersionId,
                       signed_version_id AS signedVersionId,
                       last_run_id AS lastRunId, last_run_at AS lastRunAt,
                       create_time AS createTime, update_time AS updateTime
                FROM contract_case WHERE id=? AND deleted=0
                """, caseId));
        if (c == null) throw new IllegalArgumentException("Contract case not found: " + caseId);

        c.put("parties", jdbcTemplate.queryForList(
                "SELECT id, party_name AS partyName, party_role AS partyRole, contact_person AS contactPerson, contact_email AS contactEmail, risk_score AS riskScore FROM contract_party WHERE case_id=?", caseId));
        List<Map<String, Object>> documents = jdbcTemplate.queryForList(
                "SELECT id, document_type AS documentType, file_name AS fileName,"
                + " file_size AS fileSize, version, parse_status AS parseStatus,"
                + " parse_error AS parseError, parse_provider AS parseProvider,"
                + " parse_quality AS parseQuality, parse_diagnostics_json AS parseDiagnostics,"
                + " page_count AS pageCount,"
                + " content_text IS NOT NULL AS hasInlineText,"
                + " CHAR_LENGTH(content_text) AS textLength, create_time AS createTime,"
                + " (SELECT j.id FROM contract_document_job j WHERE j.document_id=d.id ORDER BY j.id DESC LIMIT 1) AS pipelineJobId,"
                + " (SELECT j.status FROM contract_document_job j WHERE j.document_id=d.id ORDER BY j.id DESC LIMIT 1) AS pipelineStatus,"
                + " (SELECT j.stage FROM contract_document_job j WHERE j.document_id=d.id ORDER BY j.id DESC LIMIT 1) AS pipelineStage,"
                + " (SELECT j.progress FROM contract_document_job j WHERE j.document_id=d.id ORDER BY j.id DESC LIMIT 1) AS pipelineProgress,"
                + " (SELECT j.error_message FROM contract_document_job j WHERE j.document_id=d.id ORDER BY j.id DESC LIMIT 1) AS pipelineError,"
                + " (SELECT t.summary FROM contract_document_job_trace t"
                + "  JOIN contract_document_job j ON j.id=t.job_id"
                + "  WHERE j.document_id=d.id ORDER BY t.sequence_no DESC, t.id DESC LIMIT 1) AS pipelineAction"
                + " FROM contract_document d WHERE d.case_id=? AND COALESCE(d.deleted,0)=0 ORDER BY d.version DESC", caseId);
        parseJsonFields(documents, "parseDiagnostics");
        c.put("documents", documents);
        List<Map<String, Object>> findings = jdbcTemplate.queryForList("""
                SELECT f.id, f.run_id AS runId, f.rule_id AS ruleId,
                       COALESCE(f.rule_key, r.rule_key) AS ruleKey,
                       COALESCE(f.clause_type, r.clause_type) AS clauseType,
                       f.severity, f.status, f.title, f.description, f.impact,
                       f.remediation_advice AS remediationAdvice,
                       f.negotiation_advice AS negotiationAdvice,
                       f.verification_points AS verificationPoints,
                       f.contract_citation AS contractCitation,
                        f.policy_citation AS policyCitation,
                        f.suggested_action AS suggestedAction,
                        f.detail_json AS detailJson,
                        f.create_time AS createTime, f.update_time AS updateTime
                FROM contract_review_finding f
                LEFT JOIN contract_review_rule r ON r.id=f.rule_id
                WHERE f.case_id=?
                  AND f.run_id=(
                      SELECT MAX(ar.id) FROM agent_run ar
                      WHERE ar.subject_type='CONTRACT_CASE'
                        AND ar.subject_id=?
                        AND ar.run_type='CONTRACT_REVIEW'
                        AND ar.status='COMPLETED'
                  )
                ORDER BY FIELD(f.severity,'HIGH','MEDIUM','LOW'), f.id DESC
                LIMIT 30
                """, caseId, caseId);
        parseJsonFields(findings, "contractCitation", "policyCitation", "verificationPoints", "detailJson");
        c.put("findings", findings);
        c.put("obligations", jdbcTemplate.queryForList(
                "SELECT id, title, obligation_type AS obligationType, responsible_user_id AS responsibleUserId, due_date AS dueDate, status FROM contract_obligation WHERE case_id=? ORDER BY due_date ASC", caseId));
        List<Map<String, Object>> lifecycleConditions = jdbcTemplate.queryForList("""
                SELECT lc.id, lc.document_id AS documentId, lc.clause_id AS clauseId,
                       lc.condition_type AS conditionType, lc.end_mode AS endMode,
                       lc.logic_operator AS logicOperator, lc.summary,
                       lc.conditions_json AS conditions, lc.citation_json AS citation,
                       lc.confidence, lc.source, lc.status, lc.manual_override AS manualOverride,
                       lc.create_time AS createTime, lc.update_time AS updateTime
                FROM contract_lifecycle_condition lc
                WHERE lc.case_id=? AND lc.condition_type='CONTRACT_END'
                ORDER BY lc.manual_override DESC, lc.id DESC
                """, caseId);
        parseJsonFields(lifecycleConditions, "conditions", "citation");
        c.put("lifecycleConditions", lifecycleConditions);
        c.put("timelineNodes", buildTimelineNodes(c));
        c.put("availableKnowledge", knowledgeBaseService.listContractKnowledge(caseId));
        c.put("analysisWorkflow", latestAnalysisWorkflow(caseId));
        c.put("runs", jdbcTemplate.queryForList(
                "SELECT id, run_type AS runType, status, progress, current_step AS currentStep, "
                        + "workflow_id AS workflowId, workflow_stage AS workflowStage, "
                        + "evidence_snapshot_hash AS evidenceSnapshotHash, create_time AS createTime "
                        + "FROM agent_run WHERE subject_type=? AND subject_id=? ORDER BY id DESC LIMIT 10", SUBJECT_TYPE, caseId));
        List<Map<String, Object>> reports = jdbcTemplate.queryForList("""
                SELECT rp.id, rp.report_type AS reportType, rp.title, rp.summary,
                       health_status AS riskStatus, health_score AS riskScore,
                       dimensions_json AS dimensionsJson, risks_json AS risksJson,
                       plan_json AS planJson, citations_json AS citationsJson,
                       evidence_hash AS evidenceHash, analysis_mode AS analysisMode,
                       scoring_version AS scoringVersion,
                       content_json AS contentJson, report_markdown AS reportMarkdown,
                       rp.status, rp.create_time AS createTime
                FROM agent_report rp
                LEFT JOIN agent_run ar ON ar.id=rp.run_id
                WHERE (rp.subject_type=? AND rp.subject_id=?)
                   OR (ar.subject_type=? AND ar.subject_id=?)
                ORDER BY
                    CASE WHEN rp.report_type IN ('CONTRACT_REVIEW_REPORT','CONTRACT_REVIEW') THEN 0 ELSE 1 END,
                    rp.id DESC
                LIMIT 8
                """, SUBJECT_TYPE, caseId, SUBJECT_TYPE, caseId);
        parseJsonFields(reports, "dimensionsJson", "risksJson", "planJson", "citationsJson", "contentJson");
        normalizeReportRisk(reports, findings);
        c.put("reports", reports);
        c.put("reviewSummary", reports.stream()
                .filter(r -> Set.of("CONTRACT_REVIEW_REPORT", "CONTRACT_REVIEW").contains(str(r, "reportType")))
                .findFirst().orElse(Map.of()));
        // Latest pending intake for confirmation modal
        c.put("pendingIntake", first(jdbcTemplate.queryForList(
                "SELECT id, status, validated_json AS validatedJson,"
                + " schema_version AS schemaVersion, create_time AS createTime"
                + " FROM contract_intake WHERE case_id=? AND status='NEEDS_CONFIRMATION'"
                + " ORDER BY id DESC LIMIT 1", caseId)));
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
                    our_entity, counterparty, our_side, amount, currency, effective_date, expiry_date, signed_date,
                    department, owner_id, priority, tags, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'DRAFT')
                """, caseKey, title, str(request, "contractType"),
                str(request, "description"), str(request, "ourEntity"),
                str(request, "counterparty"), normalizeOurSide(str(request, "ourSide")),
                request.get("amount"), str(request, "currency"),
                request.get("effectiveDate"), request.get("expiryDate"), request.get("signedDate"),
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

    // ── Intake staging ─────────────────────────────────────────────

    @Override
    @Transactional
    public Map<String, Object> createIntake(Map<String, Object> request, Long userId) {
        String contentText = str(request, "contentText");
        String fileName = str(request, "fileName").trim();
        if (contentText.isBlank()) throw new IllegalArgumentException("请粘贴合同正文");
        if (contentText.length() > MAX_INLINE_CONTRACT_CHARS) {
            throw new IllegalArgumentException("文字合同不能超过200万字符");
        }
        if (fileName.isBlank()) fileName = "合同正文.txt";
        if (fileName.length() > 512) throw new IllegalArgumentException("文件名不能超过512个字符");

        Long intakeId = insert("""
                INSERT INTO contract_intake
                    (status, source_type, file_name, content_text, content_hash, created_by)
                VALUES ('PENDING','TEXT',?,?,?,?)
                """, fileName, contentText, sha256(contentText), userId);
        dispatchIntakeExtractionAfterCommit(intakeId);
        return getIntake(intakeId, userId);
    }

    @Override
    @Transactional
    public Map<String, Object> createFileIntake(Map<String, Object> request, Long userId) {
        String fileName = str(request, "fileName").trim();
        String filePath = str(request, "filePath").trim();
        if (fileName.isBlank()) throw new IllegalArgumentException("文件名不能为空");
        if (fileName.length() > 512) throw new IllegalArgumentException("文件名不能超过512个字符");
        if (filePath.isBlank()) throw new IllegalArgumentException("文件路径不能为空");
        String lowerName = fileName.toLowerCase(Locale.ROOT);
        if (!(lowerName.endsWith(".txt") || lowerName.endsWith(".md")
                || lowerName.endsWith(".pdf") || lowerName.endsWith(".doc")
                || lowerName.endsWith(".docx"))) {
            throw new IllegalArgumentException("当前仅支持 TXT、MD、PDF、DOC、DOCX 合同文件");
        }

        String title = fileName.replaceFirst("(?i)\\.(txt|md|pdf|docx?)$", "").trim();
        if (title.isBlank()) title = "待识别合同";
        Map<String, Object> caseRequest = new HashMap<>();
        caseRequest.put("caseKey", "CTR-" + LocalDate.now().getYear() + "-"
                + UUID.randomUUID().toString().substring(0, 8).toUpperCase(Locale.ROOT));
        caseRequest.put("title", title);
        caseRequest.put("contractType", "OTHER");
        caseRequest.put("description", "由合同文件上传发起，等待文档解析和结构化确认。");
        caseRequest.put("ownerId", userId);
        caseRequest.put("priority", "NORMAL");
        Map<String, Object> contractCase = createCase(caseRequest);
        Long caseId = numberAsLong(contractCase.get("id"));
        jdbcTemplate.update("UPDATE contract_case SET status='INTAKE_PARSING' WHERE id=?", caseId);

        Map<String, Object> documentRequest = new HashMap<>();
        documentRequest.put("documentType", "MAIN");
        documentRequest.put("fileName", fileName);
        documentRequest.put("filePath", filePath);
        documentRequest.put("fileSize", request.get("fileSize"));
        Map<String, Object> uploadResult = uploadDocument(caseId, documentRequest);

        Long intakeId = insert("""
                INSERT INTO contract_intake
                    (status, source_type, file_name, content_text, content_hash, case_id, created_by)
                VALUES ('FILE_PARSING','FILE',?,?,?,?,?)
                """, fileName, "", sha256(""), caseId, userId);
        linkAnalysisWorkflow(caseId, intakeId, numberAsLong(uploadResult.get("uploadedDocumentId")));

        Map<String, Object> result = getIntake(intakeId, userId);
        result.put("case", getCase(caseId));
        result.put("uploadedDocumentId", uploadResult.get("uploadedDocumentId"));
        result.put("documentPipelineJobId", uploadResult.get("documentPipelineJobId"));
        return result;
    }

    @Override
    public Map<String, Object> getIntake(Long intakeId, Long userId) {
        Map<String, Object> intake = first(jdbcTemplate.queryForList("""
                SELECT id, status, source_type AS sourceType, file_name AS fileName,
                       content_text AS contentText, content_hash AS contentHash,
                       validated_json AS validatedJson, schema_version AS schemaVersion,
                       prompt_version AS promptVersion, model, retry_count AS retryCount,
                       error_message AS errorMessage, case_id AS caseId,
                       create_time AS createTime, update_time AS updateTime
                FROM contract_intake WHERE id=? AND created_by=?
                """, intakeId, userId));
        if (intake == null) throw new IllegalArgumentException("合同识别任务不存在");
        Object validated = parseJson(intake.remove("validatedJson"));
        intake.put("validated", validated == null ? Map.of() : validated);
        Long caseId = numberAsLongOrNull(intake.get("caseId"));
        if (caseId != null) {
            Map<String, Object> pipeline = first(jdbcTemplate.queryForList("""
                    SELECT j.id AS pipelineJobId, j.status AS pipelineStatus,
                           j.stage AS pipelineStage, j.progress AS pipelineProgress,
                           j.error_message AS pipelineError,
                           (SELECT t.summary
                            FROM contract_document_job_trace t
                            WHERE t.job_id=j.id
                            ORDER BY t.sequence_no DESC, t.id DESC LIMIT 1) AS pipelineAction
                    FROM contract_document d
                    JOIN contract_document_job j ON j.document_id=d.id
                    WHERE d.case_id=? AND d.document_type='MAIN'
                    ORDER BY j.id DESC
                    LIMIT 1
                    """, caseId));
            if (pipeline != null) intake.putAll(pipeline);
        }
        return intake;
    }

    @Override
    @Transactional
    public Map<String, Object> retryIntake(Long intakeId, Long userId) {
        Map<String, Object> intake = lockIntake(intakeId, userId);
        if ("CONFIRMED".equals(str(intake, "status"))) {
            throw new IllegalArgumentException("已确认的合同不能重新识别");
        }
        jdbcTemplate.update("""
                UPDATE contract_intake
                SET status='PENDING', extracted_json=NULL, validated_json=NULL,
                    error_message=NULL, retry_count=retry_count+1
                WHERE id=? AND created_by=?
                """, intakeId, userId);
        dispatchIntakeExtractionAfterCommit(intakeId);
        return getIntake(intakeId, userId);
    }

    @Override
    @Transactional
    public Map<String, Object> confirmIntake(
            Long intakeId, Map<String, Object> request, Long userId) {
        Map<String, Object> intake = lockIntakeForConfirmation(intakeId, userId);
        String status = str(intake, "status");
        if ("CONFIRMED".equals(status)) {
            Long existingCaseId = numberAsLong(intake.get("caseId"));
            return Map.of("intakeId", intakeId, "status", status,
                    "case", getCase(existingCaseId));
        }
        if (!"NEEDS_CONFIRMATION".equals(status)) {
            throw new IllegalArgumentException("合同尚未完成识别，不能确认");
        }

        String title = str(request, "title").trim();
        String contractType = str(request, "contractType").trim().toUpperCase(Locale.ROOT);
        String ourEntity = str(request, "ourEntity").trim();
        String counterparty = str(request, "counterparty").trim();
        String currency = str(request, "currency").trim().toUpperCase(Locale.ROOT);
        String priority = str(request, "priority").trim().toUpperCase(Locale.ROOT);
        if (title.isBlank()) throw new IllegalArgumentException("合同标题不能为空");
        if (!CONTRACT_TYPES.contains(contractType)) throw new IllegalArgumentException("合同类型不合法");
        if (ourEntity.isBlank() || counterparty.isBlank()) {
            throw new IllegalArgumentException("请确认我方主体和相对方");
        }
        if (ourEntity.equals(counterparty)) throw new IllegalArgumentException("我方主体和相对方不能相同");
        if (currency.isBlank()) currency = "CNY";
        if (priority.isBlank()) priority = "NORMAL";
        if (!PRIORITIES.contains(priority)) throw new IllegalArgumentException("优先级不合法");

        BigDecimal amount = decimalOrNull(request.get("amount"));
        if (amount != null && amount.signum() < 0) throw new IllegalArgumentException("合同金额不能为负数");
        LocalDate effectiveDate = dateOrNull(request.get("effectiveDate"), "生效日期");
        LocalDate expiryDate = dateOrNull(request.get("expiryDate"), "到期日期");
        if (effectiveDate != null && expiryDate != null && expiryDate.isBefore(effectiveDate)) {
            throw new IllegalArgumentException("到期日期不能早于生效日期");
        }

        Map<String, Object> caseRequest = new HashMap<>();
        caseRequest.put("caseKey", "CTR-" + LocalDate.now().getYear() + "-"
                + UUID.randomUUID().toString().substring(0, 8).toUpperCase(Locale.ROOT));
        caseRequest.put("title", title);
        caseRequest.put("contractType", contractType);
        caseRequest.put("description", str(request, "description").trim());
        caseRequest.put("ourEntity", ourEntity);
        caseRequest.put("counterparty", counterparty);
        caseRequest.put("ourSide", normalizeOurSide(str(request, "ourSide")));
        caseRequest.put("amount", amount);
        caseRequest.put("currency", currency);
        caseRequest.put("effectiveDate", effectiveDate);
        caseRequest.put("expiryDate", expiryDate);
        caseRequest.put("signedDate", dateOrNull(request.get("signedDate"), "签订日期"));
        caseRequest.put("department", str(request, "department").trim());
        caseRequest.put("ownerId", userId);
        caseRequest.put("priority", priority);

        Long existingCaseId = numberAsLongOrNull(intake.get("caseId"));
        Long caseId;
        if (existingCaseId == null) {
            Map<String, Object> contractCase = createCase(caseRequest);
            caseId = numberAsLong(contractCase.get("id"));
            Map<String, Object> documentRequest = new HashMap<>();
            documentRequest.put("documentType", "MAIN");
            documentRequest.put("fileName", str(intake, "fileName"));
            documentRequest.put("filePath", "inline:text");
            documentRequest.put("contentText", str(intake, "contentText"));
            uploadDocument(caseId, documentRequest);
        } else {
            caseId = existingCaseId;
            jdbcTemplate.update("""
                    UPDATE contract_case
                    SET title=?, contract_type=?, description=?, our_entity=?,
                        counterparty=?, our_side=?, amount=?, currency=?, effective_date=?,
                        expiry_date=?, signed_date=?, department=?, owner_id=?, priority=?,
                        status='READY_FOR_REVIEW'
                    WHERE id=? AND deleted=0
                    """,
                    title, contractType, str(request, "description").trim(), ourEntity,
                    counterparty, normalizeOurSide(str(request, "ourSide")), amount, currency, effectiveDate, expiryDate,
                    dateOrNull(request.get("signedDate"), "签订日期"),
                    str(request, "department").trim(), userId, priority, caseId);
            jdbcTemplate.update("DELETE FROM contract_party WHERE case_id=?", caseId);
            jdbcTemplate.update("INSERT INTO contract_party (case_id, party_name, party_role) VALUES (?,?,'COUNTERPARTY')",
                    caseId, counterparty);
            jdbcTemplate.update("INSERT INTO contract_party (case_id, party_name, party_role) VALUES (?,?,'OUR_ENTITY')",
                    caseId, ourEntity);
        }

        jdbcTemplate.update("""
                UPDATE contract_intake
                SET status='CONFIRMED', confirmed_json=?, case_id=?, error_message=NULL
                WHERE id=?
                """, json(caseRequest), caseId, intakeId);
        markAnalysisWorkflowConfirmed(caseId, intakeId);

        return Map.of("intakeId", intakeId, "status", "CONFIRMED", "case", getCase(caseId));
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
        if (request.containsKey("ourSide")) { sets.add("our_side=?"); params.add(normalizeOurSide(str(request, "ourSide"))); }
        String[] numFields = {"amount", "ownerId"};
        for (String f : numFields) {
            if (request.containsKey(f)) { sets.add(f + "=?"); params.add(request.get(f)); }
        }
        if (request.containsKey("signedDate")) { sets.add("signed_date=?"); params.add(dateOrNull(request.get("signedDate"), "签订日期")); }
        if (request.containsKey("effectiveDate")) { sets.add("effective_date=?"); params.add(dateOrNull(request.get("effectiveDate"), "生效日期")); }
        if (request.containsKey("expiryDate")) { sets.add("expiry_date=?"); params.add(dateOrNull(request.get("expiryDate"), "到期日期")); }
        if (sets.isEmpty()) return getCase(caseId);
        params.add(caseId);
        jdbcTemplate.update("UPDATE contract_case SET " + String.join(",", sets) + " WHERE id=?", params.toArray());
        return getCase(caseId);
    }

    // ── Documents ──────────────────────────────────────────────────

    @Override
    @Transactional
    public Map<String, Object> uploadDocument(Long caseId, Map<String, Object> request) {
        String fileName = str(request, "fileName").trim();
        String contentText = str(request, "contentText");
        String documentType = str(request, "documentType").trim().toUpperCase(Locale.ROOT);
        String filePath = str(request, "filePath").trim();
        if (fileName.isBlank()) throw new IllegalArgumentException("文件名不能为空");
        if (fileName.length() > 512) throw new IllegalArgumentException("文件名不能超过512个字符");
        if (!DOCUMENT_TYPES.contains(documentType)) throw new IllegalArgumentException("合同文件类型不合法");
        if (contentText.length() > MAX_INLINE_CONTRACT_CHARS) {
            throw new IllegalArgumentException("文字合同不能超过200万字符，请改用文件上传");
        }
        if (contentText.isBlank() && filePath.isBlank()) {
            throw new IllegalArgumentException("文件路径和文字合同内容不能同时为空");
        }

        int newVersion = lockCaseAndNextDocumentVersion(caseId);
        Long documentId;

        // Inline text is parsed by Python after commit so Agent tools can read clauses.
        if (!contentText.isBlank()) {
            documentId = insert("""
                    INSERT INTO contract_document (case_id, document_type, file_name, file_path, file_size, version, content_text, parse_status)
                    VALUES (?,?,?,?,?,?,?,'PENDING')
                    """, caseId, documentType, fileName,
                    "inline:text", contentText.length(), newVersion, contentText);
            createDocumentPipelineJob(caseId, documentId, "UPLOADED", 5, "合同正文已上传，等待文档处理流水线调度",
                    Map.of("fileName", fileName, "documentType", documentType, "source", "inline-text"));
            if ("MAIN".equals(documentType)) {
                createAnalysisWorkflow(caseId, null, documentId, newVersion);
            }
            dispatchDocumentParsingAfterCommit(documentId);
        } else {
            documentId = insert("""
                    INSERT INTO contract_document (case_id, document_type, file_name, file_path, file_size, version, parse_status)
                    VALUES (?,?,?,?,?,?,'PENDING')
                    """, caseId, documentType, fileName,
                    filePath, request.get("fileSize"), newVersion);
            createDocumentPipelineJob(caseId, documentId, "UPLOADED", 5, "合同文件已登记，等待 Python Document Worker 解析",
                    Map.of("fileName", fileName, "documentType", documentType, "filePath", filePath));
            if ("MAIN".equals(documentType)) {
                createAnalysisWorkflow(caseId, null, documentId, newVersion);
            }
            dispatchDocumentParsingAfterCommit(documentId);
        }
        Map<String, Object> result = getCase(caseId);
        result.put("uploadedDocumentId", documentId);
        result.put("documentPipelineJobId", latestDocumentPipelineJobId(documentId));
        return result;
    }

    @Override
    public Map<String, Object> getDocumentContent(Long caseId, Long documentId) {
        Map<String, Object> document = first(jdbcTemplate.queryForList("""
                SELECT d.id, d.document_type AS documentType, d.file_name AS fileName,
                       d.version, d.parse_status AS parseStatus, d.content_text AS contentText
                FROM contract_document d
                JOIN contract_case c ON c.id=d.case_id AND c.deleted=0
                WHERE d.id=? AND d.case_id=?
                """, documentId, caseId));
        if (document == null) throw new IllegalArgumentException("合同文件不存在");
        if (document.get("contentText") == null) {
            throw new IllegalArgumentException("该文件没有可预览的文字内容");
        }
        return document;
    }

    @Override
    public List<Map<String, Object>> listDocuments(Long caseId) {
        List<Map<String, Object>> documents = jdbcTemplate.queryForList(
                "SELECT id, document_type AS documentType, file_name AS fileName,"
                + " file_size AS fileSize, version, parse_status AS parseStatus,"
                + " parse_error AS parseError, parse_provider AS parseProvider,"
                + " parse_quality AS parseQuality, parse_diagnostics_json AS parseDiagnostics,"
                + " page_count AS pageCount,"
                + " content_text IS NOT NULL AS hasInlineText,"
                + " CHAR_LENGTH(content_text) AS textLength, create_time AS createTime,"
                + " (SELECT j.id FROM contract_document_job j WHERE j.document_id=d.id ORDER BY j.id DESC LIMIT 1) AS pipelineJobId,"
                + " (SELECT j.status FROM contract_document_job j WHERE j.document_id=d.id ORDER BY j.id DESC LIMIT 1) AS pipelineStatus,"
                + " (SELECT j.stage FROM contract_document_job j WHERE j.document_id=d.id ORDER BY j.id DESC LIMIT 1) AS pipelineStage,"
                + " (SELECT j.progress FROM contract_document_job j WHERE j.document_id=d.id ORDER BY j.id DESC LIMIT 1) AS pipelineProgress,"
                + " (SELECT j.error_message FROM contract_document_job j WHERE j.document_id=d.id ORDER BY j.id DESC LIMIT 1) AS pipelineError,"
                + " (SELECT t.summary FROM contract_document_job_trace t"
                + "  JOIN contract_document_job j ON j.id=t.job_id"
                + "  WHERE j.document_id=d.id ORDER BY t.sequence_no DESC, t.id DESC LIMIT 1) AS pipelineAction"
                + " FROM contract_document d WHERE d.case_id=? AND COALESCE(d.deleted,0)=0 ORDER BY d.version DESC", caseId);
        parseJsonFields(documents, "parseDiagnostics");
        return documents;
    }

    @Override
    public List<Map<String, Object>> listRecentDocumentPipelines() {
        return jdbcTemplate.queryForList("""
                SELECT j.id AS jobId, j.case_id AS caseId,
                       c.case_key AS caseKey, c.title AS caseTitle,
                       j.document_id AS documentId, d.file_name AS fileName,
                       d.document_type AS documentType, d.parse_status AS parseStatus,
                       j.status, j.stage, j.progress,
                       j.error_message AS errorMessage,
                       j.started_at AS startedAt, j.finished_at AS finishedAt,
                       j.create_time AS createTime, j.update_time AS updateTime,
                       (SELECT t.summary
                        FROM contract_document_job_trace t
                        WHERE t.job_id=j.id
                        ORDER BY t.sequence_no DESC, t.id DESC LIMIT 1) AS currentAction
                FROM contract_document_job j
                JOIN contract_case c ON c.id=j.case_id AND c.deleted=0
                LEFT JOIN contract_document d ON d.id=j.document_id
                ORDER BY j.id DESC
                LIMIT 12
                """);
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

        Long workflowId = null;
        String workflowStage = null;
        String evidenceSnapshotHash = null;
        Map<String, Object> inputJson = new HashMap<>();
        Object rawInput = request.get("inputJson");
        if (rawInput instanceof Map<?, ?> map) {
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (entry.getKey() != null) inputJson.put(String.valueOf(entry.getKey()), entry.getValue());
            }
        } else {
            Object parsedInput = parseJson(rawInput);
            if (parsedInput instanceof Map<?, ?> map) {
                for (Map.Entry<?, ?> entry : map.entrySet()) {
                    if (entry.getKey() != null) inputJson.put(String.valueOf(entry.getKey()), entry.getValue());
                }
            }
        }

        if ("CONTRACT_REVIEW".equals(taskType)) {
            Map<String, Object> workflow = prepareReviewWorkflow(caseId);
            workflowId = numberAsLong(workflow.get("id"));
            workflowStage = "RISK_REVIEW";
            evidenceSnapshotHash = str(workflow, "evidenceSnapshotHash");
            Map<String, Object> analysisWorkflow = new LinkedHashMap<>();
            analysisWorkflow.put("workflowId", workflowId);
            analysisWorkflow.put("stage", workflowStage);
            analysisWorkflow.put("documentId", workflow.get("documentId"));
            analysisWorkflow.put("documentVersion", workflow.get("documentVersion"));
            analysisWorkflow.put("evidenceSnapshotHash", evidenceSnapshotHash);
            analysisWorkflow.put("confirmedVersion", workflow.get("confirmedVersion"));
            inputJson.put("analysisWorkflow", analysisWorkflow);
        }

        Long runId = insert("""
                INSERT INTO agent_run
                    (subject_type, subject_id, project_id, run_type, trigger_type, question,
                     input_json, workflow_id, workflow_stage, evidence_snapshot_hash,
                     status, progress, current_step)
                VALUES (?,?,0,?,?,?,?,?,?,?,'CREATED',0,'等待 Agent 调度')
                """, SUBJECT_TYPE, caseId, taskType,
                str(request, "triggerType"), str(request, "question"),
                json(inputJson), workflowId, workflowStage, evidenceSnapshotHash);

        if ("FULFILLMENT_CHECK".equals(taskType)) {
            Object input = request.get("inputJson");
            Map<String, Object> fulfillmentInput = input instanceof Map<?, ?> map
                    ? new HashMap<>((Map<String, Object>) map)
                    : new HashMap<>();
            Long timelineNodeId = numberAsLongOrNull(fulfillmentInput.get("timelineNodeId"));
            if (timelineNodeId != null) {
                ensureTimelineNode(caseId, timelineNodeId);
                jdbcTemplate.update("""
                        INSERT INTO contract_fulfillment_check
                            (case_id, timeline_node_id, run_id, status, summary)
                        VALUES (?,?,?,'PENDING','等待 Agent 核验履约证据')
                        """, caseId, timelineNodeId, runId);
            }
        }

        if ("CONTRACT_REVIEW".equals(taskType)) {
            jdbcTemplate.update("""
                    UPDATE contract_case
                    SET last_run_id=?, last_run_at=NOW(), status='REVIEWING'
                    WHERE id=? AND status IN ('DRAFT','MATERIAL_PENDING','READY_FOR_REVIEW','NEEDS_REVISION')
                    """, runId, caseId);
            jdbcTemplate.update("""
                    UPDATE contract_analysis_workflow
                    SET status='REVIEWING', current_stage='RISK_REVIEW', review_run_id=?, last_error=NULL
                    WHERE id=?
                    """, runId, workflowId);
        } else {
            jdbcTemplate.update("UPDATE contract_case SET last_run_id=?, last_run_at=NOW() WHERE id=?", runId, caseId);
        }

        dispatchAfterCommit(runId, caseId, taskType);
        return getRun(runId);
    }

    @Override
    @Transactional
    public Map<String, Object> startTimelineFulfillmentCheck(Long caseId, Long timelineNodeId) {
        ensureTimelineNode(caseId, timelineNodeId);
        return startRun(caseId, Map.of(
                "taskType", "FULFILLMENT_CHECK",
                "triggerType", "MANUAL",
                "question", "核验当前时间节点的履约证据、缺失项和验收风险",
                "inputJson", Map.of("timelineNodeId", timelineNodeId)
        ));
    }

    @Override
    @Transactional
    public Map<String, Object> confirmFulfillmentCheck(Long checkId, Map<String, Object> request, String actor) {
        Map<String, Object> check = first(jdbcTemplate.queryForList("""
                SELECT id, case_id AS caseId
                FROM contract_fulfillment_check
                WHERE id=?
                FOR UPDATE
                """, checkId));
        if (check == null) throw new IllegalArgumentException("履约核验记录不存在");
        String result = str(request, "manualResult").trim().toUpperCase(Locale.ROOT);
        if (result.isBlank()) result = str(request, "result").trim().toUpperCase(Locale.ROOT);
        if (!Set.of("COMPLETED", "FAILED", "PENDING", "NEEDS_MORE_EVIDENCE").contains(result)) {
            throw new IllegalArgumentException("人工确认结果不合法");
        }
        String note = str(request, "manualNote").trim();
        if (note.isBlank()) note = str(request, "note").trim();
        if (note.isBlank()) throw new IllegalArgumentException("请填写人工确认说明");
        jdbcTemplate.update("""
                UPDATE contract_fulfillment_check
                SET manual_result=?, manual_note=?, confirmed_by=?, confirmed_at=NOW()
                WHERE id=?
                """, result, note, actor == null || actor.isBlank() ? "authenticated-user" : actor, checkId);
        return getCase(numberAsLong(check.get("caseId")));
    }

    @Override
    public Map<String, Object> getTimelineEvidenceLinks(Long caseId, Long timelineNodeId) {
        ensureTimelineNode(caseId, timelineNodeId);
        List<Map<String, Object>> available = jdbcTemplate.queryForList("""
                SELECT d.id, d.document_type AS documentType, d.file_name AS fileName,
                       d.file_size AS fileSize, d.version, d.parse_status AS parseStatus,
                       d.content_hash AS contentHash, d.update_time AS updateTime,
                       EXISTS (
                         SELECT 1 FROM contract_timeline_evidence_link l
                         WHERE l.case_id=d.case_id
                           AND l.timeline_node_id=?
                           AND l.document_id=d.id
                           AND l.check_id IS NULL
                           AND COALESCE(l.deleted,0)=0
                       ) AS linked
                FROM contract_document d
                WHERE d.case_id=?
                  AND d.document_type IN ('FULFILLMENT_EVIDENCE','ATTACHMENT','CERTIFICATE','PRICING')
                  AND COALESCE(d.deleted,0)=0
                  AND d.parse_status <> 'FAILED'
                ORDER BY linked DESC,
                         FIELD(d.document_type,'FULFILLMENT_EVIDENCE','ATTACHMENT','CERTIFICATE','PRICING'),
                         d.version DESC, d.id DESC
                """, timelineNodeId, caseId);
        List<Long> linkedDocumentIds = available.stream()
                .filter(row -> Boolean.TRUE.equals(row.get("linked"))
                        || "1".equals(String.valueOf(row.get("linked"))))
                .map(row -> numberAsLong(row.get("id")))
                .toList();
        return Map.of(
                "caseId", caseId,
                "timelineNodeId", timelineNodeId,
                "available", available,
                "linkedDocumentIds", linkedDocumentIds
        );
    }

    @Override
    @Transactional
    public Map<String, Object> saveTimelineEvidenceLinks(
            Long caseId, Long timelineNodeId, Map<String, Object> request) {
        ensureTimelineNode(caseId, timelineNodeId);
        Set<Long> requestedIds = new LinkedHashSet<>();
        Object rawIds = request.get("documentIds");
        if (rawIds instanceof Collection<?> collection) {
            for (Object value : collection) {
                Long id = numberAsLongOrNull(value);
                if (id != null) requestedIds.add(id);
            }
        }
        if (requestedIds.size() > 50) throw new IllegalArgumentException("一次最多绑定 50 份证据");

        Map<Long, Map<String, Object>> allowed = new HashMap<>();
        if (!requestedIds.isEmpty()) {
            String placeholders = String.join(",", Collections.nCopies(requestedIds.size(), "?"));
            List<Object> params = new ArrayList<>();
            params.add(caseId);
            params.addAll(requestedIds);
            List<Map<String, Object>> documents = jdbcTemplate.queryForList("""
                    SELECT id, version, content_hash AS contentHash
                    FROM contract_document
                    WHERE case_id=?
                      AND id IN (%s)
                      AND document_type IN ('FULFILLMENT_EVIDENCE','ATTACHMENT','CERTIFICATE','PRICING')
                      AND COALESCE(deleted,0)=0
                      AND parse_status <> 'FAILED'
                    """.formatted(placeholders), params.toArray());
            for (Map<String, Object> document : documents) {
                allowed.put(numberAsLong(document.get("id")), document);
            }
            if (allowed.size() != requestedIds.size()) {
                throw new IllegalArgumentException("存在不可用于该合同的证据文件");
            }
        }

        jdbcTemplate.update("""
                UPDATE contract_timeline_evidence_link
                SET deleted=1
                WHERE case_id=? AND timeline_node_id=? AND check_id IS NULL
                """, caseId, timelineNodeId);
        for (Long documentId : requestedIds) {
            Map<String, Object> document = allowed.get(documentId);
            Map<String, Object> existing = first(jdbcTemplate.queryForList("""
                    SELECT id FROM contract_timeline_evidence_link
                    WHERE case_id=? AND timeline_node_id=? AND document_id=?
                      AND check_id IS NULL
                    ORDER BY id DESC LIMIT 1
                    """, caseId, timelineNodeId, documentId));
            if (existing == null) {
                jdbcTemplate.update("""
                        INSERT INTO contract_timeline_evidence_link
                            (case_id, timeline_node_id, document_id, check_id,
                             link_source, relation_type, evidence_version, evidence_hash, deleted)
                        VALUES (?,?,?,NULL,'MANUAL','FULFILLMENT_EVIDENCE',?,?,0)
                        """, caseId, timelineNodeId, documentId,
                        document.get("version"), document.get("contentHash"));
            } else {
                jdbcTemplate.update("""
                        UPDATE contract_timeline_evidence_link
                        SET deleted=0, link_source='MANUAL',
                            evidence_version=?, evidence_hash=?, update_time=NOW()
                        WHERE id=?
                        """, document.get("version"), document.get("contentHash"), existing.get("id"));
            }
        }
        return getTimelineEvidenceLinks(caseId, timelineNodeId);
    }

    @Override
    public List<Map<String, Object>> listRuns(Long caseId) {
        return jdbcTemplate.queryForList("""
                SELECT id, run_type AS runType, status, progress, current_step AS currentStep,
                       workflow_id AS workflowId, workflow_stage AS workflowStage,
                       evidence_snapshot_hash AS evidenceSnapshotHash,
                       error_message AS errorMessage, create_time AS createTime
                FROM agent_run WHERE subject_type=? AND subject_id=? ORDER BY id DESC LIMIT 20
                """, SUBJECT_TYPE, caseId);
    }

    @Override
    public Map<String, Object> getRun(Long runId) {
        Map<String, Object> run = first(jdbcTemplate.queryForList("""
                SELECT id, subject_type AS subjectType, subject_id AS subjectId, run_type AS runType,
                       status, progress, current_step AS currentStep, error_message AS errorMessage,
                       workflow_id AS workflowId, workflow_stage AS workflowStage,
                       evidence_snapshot_hash AS evidenceSnapshotHash,
                       create_time AS createTime
                FROM agent_run WHERE id=? AND subject_type=?
                """, runId, SUBJECT_TYPE));
        if (run == null) throw new IllegalArgumentException("Run not found");
        return run;
    }

    @Override
    @Transactional
    public Map<String, Object> updateFinding(Long findingId, Map<String, Object> request) {
        Map<String, Object> finding = first(jdbcTemplate.queryForList("""
                SELECT id, case_id AS caseId, status
                FROM contract_review_finding
                WHERE id=?
                FOR UPDATE
                """, findingId));
        if (finding == null) throw new IllegalArgumentException("审查发现不存在");

        String status = str(request, "status").trim().toUpperCase(Locale.ROOT);
        if (status.isBlank()) status = "OPEN";
        if (!Set.of("OPEN", "REMEDIATED", "ACCEPTED_EXCEPTION", "DISMISSED").contains(status)) {
            throw new IllegalArgumentException("审查发现状态不合法");
        }
        Long resolver = request.get("resolvedBy") instanceof Number n ? n.longValue() : null;
        if ("OPEN".equals(status)) {
            jdbcTemplate.update("""
                    UPDATE contract_review_finding
                    SET status='OPEN', resolved_by=NULL, resolved_at=NULL
                    WHERE id=?
                    """, findingId);
        } else {
            jdbcTemplate.update("""
                    UPDATE contract_review_finding
                    SET status=?, resolved_by=?, resolved_at=NOW()
                    WHERE id=?
                    """, status, resolver, findingId);
        }

        Long caseId = numberAsLong(finding.get("caseId"));
        Integer openCount = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_review_finding WHERE case_id=? AND status='OPEN'",
                Integer.class, caseId);
        if (openCount != null && openCount == 0) {
            jdbcTemplate.update("""
                    UPDATE contract_case
                    SET status='PENDING_APPROVAL'
                    WHERE id=? AND status='NEEDS_REVISION' AND deleted=0
                    """, caseId);
        }
        return getCase(caseId);
    }

    @Override
    @Transactional
    public Map<String, Object> approveAction(Long runId, Long actionId, Map<String, Object> request, String approvedBy) {
        Map<String, Object> action = first(jdbcTemplate.queryForList("""
                SELECT a.id FROM agent_action a
                JOIN agent_run r ON r.id=a.run_id AND r.subject_type=?
                WHERE a.id=? AND a.run_id=?
                """, SUBJECT_TYPE, actionId, runId));
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
                FROM agent_action a
                JOIN agent_run r ON r.id=a.run_id AND r.subject_type=?
                WHERE a.id=? AND a.run_id=?
                """, SUBJECT_TYPE, actionId, runId));
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
            Map<String, Object> run = first(jdbcTemplate.queryForList(
                    "SELECT question, input_json AS inputJson, workflow_id AS workflowId, "
                            + "workflow_stage AS workflowStage, evidence_snapshot_hash AS evidenceSnapshotHash "
                            + "FROM agent_run WHERE id=?", runId));
            Object taskInput = run == null ? Map.of() : parseJson(run.get("inputJson"));
            if (!(taskInput instanceof Map<?, ?>)) taskInput = Map.of();
            Map<String, Object> payload = new HashMap<>();
            payload.put("requestId", UUID.randomUUID().toString());
            payload.put("subjectType", SUBJECT_TYPE);
            payload.put("subjectId", caseId);
            payload.put("runId", runId);
            payload.put("taskType", taskType);
            payload.put("goal", "Contract case " + (c != null ? str(c, "caseKey") : "#" + caseId));
            payload.put("project", c != null ? c : Map.of());
            payload.put("question", run == null ? "" : str(run, "question"));
            payload.put("actor", "java-service");
            payload.put("taskInput", taskInput);
            if (run != null) {
                payload.put("workflowId", run.get("workflowId"));
                payload.put("workflowStage", run.get("workflowStage"));
                payload.put("evidenceSnapshotHash", run.get("evidenceSnapshotHash"));
            }
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
        Map<String, Object> evidenceRequest = new HashMap<>(request);
        evidenceRequest.put("documentType", "FULFILLMENT_EVIDENCE");
        return uploadDocument(caseId, evidenceRequest);
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

    private Long createAnalysisWorkflow(Long caseId, Long intakeId, Long documentId, Integer documentVersion) {
        if (documentId != null) {
            Map<String, Object> existing = first(jdbcTemplate.queryForList(
                    "SELECT id FROM contract_analysis_workflow WHERE case_id=? AND document_id=? ORDER BY id DESC LIMIT 1",
                    caseId, documentId));
            if (existing != null) return numberAsLong(existing.get("id"));
        }
        return insert("""
                INSERT INTO contract_analysis_workflow
                    (case_id, intake_id, document_id, document_version, status, current_stage)
                VALUES (?,?,?,?, 'PARSING', 'DOCUMENT_PARSE')
                """, caseId, intakeId, documentId, documentVersion);
    }

    private void linkAnalysisWorkflow(Long caseId, Long intakeId, Long documentId) {
        if (caseId == null || intakeId == null || documentId == null) return;
        Map<String, Object> workflow = first(jdbcTemplate.queryForList(
                "SELECT id FROM contract_analysis_workflow WHERE case_id=? AND document_id=? ORDER BY id DESC LIMIT 1",
                caseId, documentId));
        if (workflow != null) {
            jdbcTemplate.update("UPDATE contract_analysis_workflow SET intake_id=? WHERE id=?",
                    intakeId, workflow.get("id"));
        }
    }

    private Map<String, Object> latestAnalysisWorkflow(Long caseId) {
        Map<String, Object> workflow = first(jdbcTemplate.queryForList("""
                SELECT id, case_id AS caseId, intake_id AS intakeId, document_id AS documentId,
                       document_version AS documentVersion, evidence_snapshot_hash AS evidenceSnapshotHash,
                       confirmed_version AS confirmedVersion, status, current_stage AS currentStage,
                       review_run_id AS reviewRunId, last_error AS lastError,
                       confirmed_at AS confirmedAt, create_time AS createTime, update_time AS updateTime
                FROM contract_analysis_workflow
                WHERE case_id=?
                ORDER BY id DESC LIMIT 1
                """, caseId));
        return workflow == null ? Map.of() : workflow;
    }

    private void markAnalysisWorkflowConfirmed(Long caseId, Long intakeId) {
        Map<String, Object> workflow = first(jdbcTemplate.queryForList("""
                SELECT id, document_id AS documentId
                FROM contract_analysis_workflow
                WHERE case_id=? AND (intake_id=? OR intake_id IS NULL)
                ORDER BY id DESC LIMIT 1
                """, caseId, intakeId));
        if (workflow == null) return;

        Map<String, Object> document = first(jdbcTemplate.queryForList("""
                SELECT parse_status AS parseStatus
                FROM contract_document WHERE id=? AND case_id=? AND COALESCE(deleted,0)=0
                """, workflow.get("documentId"), caseId));
        boolean ready = document != null && "READY".equalsIgnoreCase(str(document, "parseStatus"));
        jdbcTemplate.update("""
                UPDATE contract_analysis_workflow
                SET intake_id=?, confirmed_version=confirmed_version+1,
                    status=?, current_stage=?, confirmed_at=NOW(), last_error=NULL
                WHERE id=?
                """, intakeId, ready ? "READY_FOR_REVIEW" : "PARSING",
                ready ? "RISK_REVIEW" : "DOCUMENT_PARSE", workflow.get("id"));
    }

    private Map<String, Object> prepareReviewWorkflow(Long caseId) {
        Map<String, Object> workflow = latestAnalysisWorkflow(caseId);
        if (workflow.isEmpty()) {
            Map<String, Object> document = first(jdbcTemplate.queryForList("""
                    SELECT id, version, content_hash AS contentHash, content_text AS contentText
                    FROM contract_document
                    WHERE case_id=? AND document_type='MAIN' AND parse_status='READY'
                      AND COALESCE(deleted,0)=0
                    ORDER BY version DESC, id DESC LIMIT 1
                    """, caseId));
            if (document == null) {
                throw new IllegalArgumentException("合同文档尚未解析完成，暂不能发起风险审查");
            }
            Long workflowId = createAnalysisWorkflow(
                    caseId, null, numberAsLong(document.get("id")),
                    intValue(document.get("version"), 1));
            jdbcTemplate.update("""
                    UPDATE contract_analysis_workflow
                    SET evidence_snapshot_hash=?, status='READY_FOR_REVIEW', current_stage='RISK_REVIEW'
                    WHERE id=?
                    """, str(document, "contentHash").isBlank()
                            ? sha256(str(document, "contentText")) : str(document, "contentHash"), workflowId);
            workflow = latestAnalysisWorkflow(caseId);
        }

        String status = str(workflow, "status").toUpperCase(Locale.ROOT);
        String stage = str(workflow, "currentStage").toUpperCase(Locale.ROOT);
        if ("PARSING".equals(status)) {
            throw new IllegalArgumentException("合同文档仍在解析，完成后才能发起风险审查");
        }
        if ("WAITING_CONFIRMATION".equals(status)) {
            throw new IllegalArgumentException("请先确认合同识别结果，再发起风险审查");
        }
        if ("FAILED".equals(status) && !"RISK_REVIEW".equals(stage)) {
            throw new IllegalArgumentException("合同文档解析失败，请先重新解析合同");
        }
        if ("REVIEWING".equals(status)) {
            Long activeRunId = numberAsLongOrNull(workflow.get("reviewRunId"));
            if (activeRunId != null) {
                Map<String, Object> activeRun = first(jdbcTemplate.queryForList(
                        "SELECT status FROM agent_run WHERE id=?", activeRunId));
                if (activeRun != null && Set.of("CREATED", "CONTEXT_BUILDING", "PLANNING",
                        "ANALYZING", "VERIFYING").contains(str(activeRun, "status").toUpperCase(Locale.ROOT))) {
                    throw new IllegalArgumentException("合同风险审查已经在运行中，请等待当前任务完成");
                }
            }
        }
        if (str(workflow, "evidenceSnapshotHash").isBlank()) {
            throw new IllegalArgumentException("合同证据快照尚未生成，暂不能发起风险审查");
        }
        return workflow;
    }

    private int lockCaseAndNextDocumentVersion(Long caseId) {
        Map<String, Object> contractCase = first(jdbcTemplate.queryForList(
                "SELECT id FROM contract_case WHERE id=? AND deleted=0 FOR UPDATE", caseId));
        if (contractCase == null) throw new IllegalArgumentException("合同案件不存在");
        Integer maxVersion = jdbcTemplate.queryForObject(
                "SELECT COALESCE(MAX(version), 0) FROM contract_document WHERE case_id=?",
                Integer.class, caseId);
        return (maxVersion == null ? 0 : maxVersion) + 1;
    }

    private void ensureTimelineNode(Long caseId, Long timelineNodeId) {
        if (timelineNodeId == null) throw new IllegalArgumentException("时间节点不能为空");
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM contract_timeline_node WHERE id=? AND case_id=?",
                Integer.class, timelineNodeId, caseId);
        if (count == null || count == 0) {
            throw new IllegalArgumentException("时间节点不存在或不属于当前合同");
        }
    }

    private void dispatchDocumentParsingAfterCommit(Long documentId) {
        Runnable dispatch = () -> {
            try {
                aiGateway.parseContractDocument(documentId);
            } catch (Exception e) {
                failLatestDocumentPipelineJob(documentId, "DISPATCH_FAILED",
                        "合同解析服务不可用: " + e.getMessage());
                jdbcTemplate.update(
                        "UPDATE contract_document SET parse_status='FAILED', parse_error=? WHERE id=?",
                        "合同解析服务不可用: " + e.getMessage(), documentId);
            }
        };
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            dispatch.run();
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                dispatch.run();
            }
        });
    }

    private Long createDocumentPipelineJob(Long caseId, Long documentId, String stage,
                                           int progress, String summary,
                                           Map<String, Object> input) {
        Long jobId = insert("""
                INSERT INTO contract_document_job
                (case_id, document_id, job_type, status, stage, progress, started_at)
                VALUES (?,?,'CONTRACT_DOCUMENT_PIPELINE','UPLOADED',?,?,NOW())
                """, caseId, documentId, stage, progress);
        appendDocumentPipelineTrace(jobId, stage, summary, input, Map.of(), null);
        return jobId;
    }

    private void appendDocumentPipelineTrace(Long jobId, String stage, String summary,
                                             Map<String, Object> input,
                                             Map<String, Object> output,
                                             String errorMessage) {
        Integer nextSeq = jdbcTemplate.queryForObject("""
                SELECT COALESCE(MAX(sequence_no), 0) + 1
                FROM contract_document_job_trace
                WHERE job_id=?
                """, Integer.class, jobId);
        jdbcTemplate.update("""
                INSERT INTO contract_document_job_trace
                (job_id, stage, sequence_no, summary, input_json, output_json, error_message)
                VALUES (?,?,?,?,?,?,?)
                """, jobId, stage, nextSeq == null ? 1 : nextSeq,
                summary, json(input), json(output), errorMessage);
    }

    private Long latestDocumentPipelineJobId(Long documentId) {
        List<Map<String, Object>> rows = jdbcTemplate.queryForList("""
                SELECT id FROM contract_document_job
                WHERE document_id=?
                ORDER BY id DESC LIMIT 1
                """, documentId);
        if (rows.isEmpty()) return null;
        return numberAsLong(rows.get(0).get("id"));
    }

    private void failLatestDocumentPipelineJob(Long documentId, String stage, String message) {
        Long jobId = latestDocumentPipelineJobId(documentId);
        if (jobId == null) return;
        jdbcTemplate.update("""
                UPDATE contract_document_job
                SET status='FAILED', stage=?, progress=100, error_message=?, finished_at=NOW()
                WHERE id=?
                """, stage, message, jobId);
        appendDocumentPipelineTrace(jobId, stage, message,
                Map.of("documentId", documentId), Map.of(), message);
    }

    private void dispatchIntakeExtractionAfterCommit(Long intakeId) {
        Runnable dispatch = () -> {
            try {
                aiGateway.extractContractIntake(intakeId);
            } catch (Exception e) {
                jdbcTemplate.update("""
                        UPDATE contract_intake SET status='FAILED', error_message=? WHERE id=?
                        """, "合同识别服务不可用: " + e.getMessage(), intakeId);
            }
        };
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            dispatch.run();
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                dispatch.run();
            }
        });
    }

    private Map<String, Object> lockIntake(Long intakeId, Long userId) {
        Map<String, Object> intake = first(jdbcTemplate.queryForList("""
                SELECT id, status, file_name AS fileName, content_text AS contentText,
                       case_id AS caseId
                FROM contract_intake WHERE id=? AND created_by=? FOR UPDATE
                """, intakeId, userId));
        if (intake == null) throw new IllegalArgumentException("合同识别任务不存在");
        return intake;
    }

    private Map<String, Object> lockIntakeForConfirmation(Long intakeId, Long userId) {
        Map<String, Object> intake = first(jdbcTemplate.queryForList("""
                SELECT i.id, i.status, i.file_name AS fileName, i.content_text AS contentText,
                       i.case_id AS caseId
                FROM contract_intake i
                LEFT JOIN contract_case c ON c.id=i.case_id AND c.deleted=0
                WHERE i.id=?
                  AND (
                    i.created_by=?
                    OR (i.case_id IS NOT NULL AND (c.owner_id=? OR i.created_by IS NULL))
                  )
                FOR UPDATE
                """, intakeId, userId, userId));
        if (intake == null) throw new IllegalArgumentException("合同识别任务不存在");
        return intake;
    }

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

    private Object parseJson(Object value) {
        if (value == null) return null;
        try { return objectMapper.readValue(String.valueOf(value), Object.class); }
        catch (Exception e) { return null; }
    }

    private void parseJsonFields(List<Map<String, Object>> rows, String... fields) {
        for (Map<String, Object> row : rows) {
            for (String field : fields) {
                Object parsed = parseJson(row.get(field));
                if (parsed != null) row.put(field, parsed);
            }
        }
    }

    private void normalizeReportRisk(List<Map<String, Object>> reports, List<Map<String, Object>> findings) {
        long openHigh = findings.stream()
                .filter(f -> "OPEN".equals(str(f, "status")))
                .filter(f -> "HIGH".equals(str(f, "severity")))
                .count();
        long openMedium = findings.stream()
                .filter(f -> "OPEN".equals(str(f, "status")))
                .filter(f -> "MEDIUM".equals(str(f, "severity")))
                .count();
        long openLow = findings.stream()
                .filter(f -> "OPEN".equals(str(f, "status")))
                .filter(f -> "LOW".equals(str(f, "severity")))
                .count();
        if (openHigh + openMedium + openLow == 0) return;

        int fallbackScore = Math.max(0, 100 - (int) openHigh * 25 - (int) openMedium * 12 - (int) openLow * 5);
        for (Map<String, Object> report : reports) {
            if (!"CONTRACT_REVIEW_REPORT".equals(str(report, "reportType"))) continue;
            int score = intValue(report.get("riskScore"), fallbackScore);
            if (score == 0) score = fallbackScore;
            if (openHigh > 0 && score >= 80) score = 79;
            report.put("riskScore", score);
            if (openHigh > 0 && "LOW_RISK".equals(str(report, "riskStatus"))) {
                report.put("riskStatus", "MEDIUM_RISK");
            } else if (str(report, "riskStatus").isBlank()) {
                report.put("riskStatus", score >= 80 ? "LOW_RISK" : score >= 60 ? "MEDIUM_RISK" : "HIGH_RISK");
            }
        }
    }

    private void attachTimelineNodes(List<Map<String, Object>> cases) {
        for (Map<String, Object> c : cases) {
            try {
                c.put("timelineNodes", buildTimelineNodes(c));
            } catch (Exception ignored) {
                c.put("timelineNodes", List.of());
            }
        }
    }

    private List<Map<String, Object>> buildTimelineNodes(Map<String, Object> contractCase) {
        Long caseId = numberAsLong(contractCase.get("id"));
        List<Map<String, Object>> nodes = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();

        addTimelineNode(nodes, seen, "CONTRACT_START", "合同开始", objectDate(contractCase.get("effectiveDate")),
                null, "CASE_FIELD", caseId, str(contractCase, "title"),
                "来自合同案件的生效日期", "CASE_FIELD", "PLANNED");
        addTimelineNode(nodes, seen, "CONTRACT_END", "合同结束/到期", objectDate(contractCase.get("expiryDate")),
                null, "CASE_FIELD", caseId, str(contractCase, "title"),
                "来自合同案件的到期日期", "CASE_FIELD", "PLANNED");

        List<Map<String, Object>> extractedNodes = jdbcTemplate.queryForList("""
                SELECT n.id, n.node_type AS nodeType, n.label,
                       n.node_date AS nodeDate, n.condition_text AS conditionText,
                       n.business_meaning AS businessMeaning,
                       n.responsible_party AS responsibleParty,
                       n.source, n.status, n.confidence, n.citation_json AS citationJson,
                       c.clause_number AS clauseNumber, c.title AS clauseTitle,
                       c.content AS clauseContent
                FROM contract_timeline_node n
                LEFT JOIN contract_clause c ON c.id=n.clause_id
                WHERE n.case_id=?
                ORDER BY COALESCE(n.node_date, '9999-12-31'), n.id
                LIMIT 80
                """, caseId);
        for (Map<String, Object> node : extractedNodes) {
            Object citation = parseJson(node.get("citationJson"));
            if (isLegacyNoisyTimelineNode(node, citation)) continue;
            String sourceTitle = String.join(" ",
                    str(node, "clauseNumber"), str(node, "clauseTitle")).trim();
            String description = cleanTimelineBusinessMeaning(str(node, "businessMeaning"));
            if (description.isBlank()) {
                description = "来自合同文档流水线的可追溯时间节点";
            }
            Map<String, Object> added = addTimelineNode(nodes, seen, str(node, "nodeType"), str(node, "label"),
                    objectDate(node.get("nodeDate")), str(node, "conditionText"),
                    "PIPELINE_TIMELINE", node.get("id"), sourceTitle,
                    description, str(node, "source"), str(node, "status"));
            if (added != null) {
                if (citation instanceof Map<?, ?> parsedCitation) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> citationMap = (Map<String, Object>) parsedCitation;
                    if (str(citationMap, "fullQuote").isBlank()) {
                        citationMap.put("fullQuote", str(node, "clauseContent"));
                    }
                    added.put("citation", citationMap);
                }
                added.put("confidence", node.get("confidence"));
                added.put("responsibleParty", str(node, "responsibleParty"));
                added.put("source", str(node, "source"));
            }
        }

        List<Map<String, Object>> obligations = jdbcTemplate.queryForList("""
                SELECT id, title, obligation_type AS obligationType,
                       due_date AS dueDate, trigger_condition AS triggerCondition,
                       status, evidence_required AS evidenceRequired
                FROM contract_obligation
                WHERE case_id=?
                ORDER BY due_date ASC, id ASC
                """, caseId);
        for (Map<String, Object> obligation : obligations) {
            String title = str(obligation, "title");
            String trigger = str(obligation, "triggerCondition");
            String description = trigger.isBlank()
                    ? "来自 Agent 或人工沉淀的履约义务"
                    : "触发条件：" + trigger;
            addTimelineNode(nodes, seen, str(obligation, "obligationType"), title,
                    objectDate(obligation.get("dueDate")), trigger,
                    "OBLIGATION", obligation.get("id"), title,
                    description, "AGENT_OBLIGATION", str(obligation, "status"));
        }

        if (extractedNodes.isEmpty()) {
            List<Map<String, Object>> clauses = jdbcTemplate.queryForList("""
                    SELECT id, clause_type AS clauseType, clause_number AS clauseNumber,
                           title, content
                    FROM contract_clause
                    WHERE case_id=?
                    ORDER BY id ASC
                    LIMIT 160
                    """, caseId);
            Integer inferredYear = Optional.ofNullable(objectDate(contractCase.get("effectiveDate")))
                    .map(LocalDate::getYear)
                    .orElseGet(() -> LocalDate.now().getYear());
            for (Map<String, Object> clause : clauses) {
                extractClauseTimeNodes(nodes, seen, clause, inferredYear);
            }
        }

        nodes.sort((a, b) -> {
            LocalDate da = objectDate(a.get("date"));
            LocalDate db = objectDate(b.get("date"));
            if (da != null && db != null) return da.compareTo(db);
            if (da != null) return -1;
            if (db != null) return 1;
            return String.valueOf(a.getOrDefault("label", ""))
                    .compareTo(String.valueOf(b.getOrDefault("label", "")));
        });
        attachFulfillmentChecks(caseId, nodes);
        return nodes;
    }

    private String cleanTimelineBusinessMeaning(String value) {
        if (value == null) return "";
        String cleaned = value.replaceAll("[；;]\\s*来源\\s*=\\s*[A-Z0-9_]+\\s*", "")
                .replaceAll("[；;]\\s*原文片段\\s*[:：].*$", "")
                .replaceAll("来源\\s*=\\s*(DURATION_TERM|TEXT_DATE(_INFERRED_YEAR)?|RELATIVE_TERM)(_RESOLVED)?", "")
                .trim();
        return cleaned.replaceAll("[；;，,\\s]+$", "");
    }

    private boolean isLegacyNoisyTimelineNode(Map<String, Object> node, Object citation) {
        if (!"RULE_EXTRACTED".equalsIgnoreCase(str(node, "source"))) return false;
        if (!(citation instanceof Map<?, ?> citationMap)) return false;
        Object extractionMode = citationMap.get("extractionMode");
        String mode = extractionMode == null ? "" : String.valueOf(extractionMode).toUpperCase(Locale.ROOT);
        return mode.equals("TEXT_DATE") || mode.equals("TEXT_DATE_INFERRED_YEAR");
    }

    private void attachFulfillmentChecks(Long caseId, List<Map<String, Object>> nodes) {
        List<Map<String, Object>> checks = jdbcTemplate.queryForList("""
                SELECT fc.id, fc.timeline_node_id AS timelineNodeId, fc.run_id AS runId,
                       fc.status, fc.conclusion, fc.risk_level AS riskLevel,
                       fc.confidence_level AS confidenceLevel, fc.summary,
                       fc.requirement_json AS requirementJson,
                       fc.evidence_snapshot_json AS evidenceSnapshotJson,
                       fc.missing_evidence_json AS missingEvidenceJson,
                       fc.explicit_consequence AS explicitConsequence,
                       fc.ai_risk AS aiRisk,
                       fc.suggested_actions_json AS suggestedActionsJson,
                       fc.manual_result AS manualResult, fc.manual_note AS manualNote,
                       fc.confirmed_by AS confirmedBy, fc.confirmed_at AS confirmedAt,
                       fc.create_time AS createTime, fc.update_time AS updateTime,
                       r.status AS runStatus, r.progress AS runProgress,
                       r.current_step AS runCurrentStep,
                       (EXISTS (
                         SELECT 1 FROM contract_document d
                         WHERE d.case_id=fc.case_id
                           AND d.document_type IN ('FULFILLMENT_EVIDENCE','ATTACHMENT','CERTIFICATE','PRICING')
                           AND COALESCE(d.deleted,0)=0
                           AND d.parse_status <> 'FAILED'
                           AND d.update_time > COALESCE(fc.update_time, fc.create_time)
                       ) OR EXISTS (
                         SELECT 1 FROM contract_timeline_evidence_link l
                         WHERE l.case_id=fc.case_id
                           AND l.timeline_node_id=fc.timeline_node_id
                           AND l.check_id IS NULL
                           AND l.update_time > COALESCE(fc.update_time, fc.create_time)
                       )) AS needsRecheck
                FROM contract_fulfillment_check fc
                LEFT JOIN agent_run r ON r.id=fc.run_id
                WHERE fc.case_id=?
                ORDER BY fc.timeline_node_id ASC, fc.id DESC
                """, caseId);
        parseJsonFields(checks, "requirementJson", "evidenceSnapshotJson",
                "missingEvidenceJson", "suggestedActionsJson");
        Map<Long, List<Map<String, Object>>> byNode = new HashMap<>();
        for (Map<String, Object> check : checks) {
            Long nodeId = numberAsLongOrNull(check.get("timelineNodeId"));
            if (nodeId == null) continue;
            byNode.computeIfAbsent(nodeId, ignored -> new ArrayList<>()).add(check);
        }
        for (Map<String, Object> node : nodes) {
            if (!"PIPELINE_TIMELINE".equals(str(node, "sourceType"))) continue;
            Long nodeId = numberAsLongOrNull(node.get("sourceId"));
            if (nodeId == null) continue;
            List<Map<String, Object>> history = byNode.getOrDefault(nodeId, List.of());
            node.put("fulfillmentCheckHistory", history);
            node.put("latestFulfillmentCheck", history.isEmpty() ? null : history.get(0));
        }
    }

    private void extractClauseTimeNodes(List<Map<String, Object>> nodes, Set<String> seen,
                                        Map<String, Object> clause, int inferredYear) {
        String content = str(clause, "content");
        if (content.isBlank()) return;

        Matcher absolute = ABSOLUTE_DATE_PATTERN.matcher(content);
        while (absolute.find()) {
            LocalDate date = safeDate(absolute.group(1), absolute.group(2), absolute.group(3));
            String snippet = snippetAround(content, absolute.start(), absolute.end());
            addTimelineNode(nodes, seen, str(clause, "clauseType"),
                    timelineLabel(str(clause, "clauseType"), snippet),
                    date, null, "CLAUSE_DATE", clause.get("id"),
                    clauseTitle(clause), snippet, "TEXT_DATE", "PLANNED");
        }

        Matcher monthDay = MONTH_DAY_PATTERN.matcher(content);
        while (monthDay.find()) {
            String matched = monthDay.group(0);
            if (content.substring(Math.max(0, monthDay.start() - 5), monthDay.start()).matches(".*20\\d{2}[-年./]$")) {
                continue;
            }
            LocalDate date = safeDate(String.valueOf(inferredYear), monthDay.group(1), monthDay.group(2));
            String snippet = snippetAround(content, monthDay.start(), monthDay.end());
            addTimelineNode(nodes, seen, str(clause, "clauseType"),
                    timelineLabel(str(clause, "clauseType"), snippet),
                    date, null, "CLAUSE_DATE", clause.get("id"),
                    clauseTitle(clause), snippet, "TEXT_DATE_INFERRED_YEAR", "PLANNED");
        }

        Matcher relative = RELATIVE_TERM_PATTERN.matcher(content);
        while (relative.find()) {
            String snippet = snippetAround(content, relative.start(), relative.end());
            String condition = relative.group(0);
            addTimelineNode(nodes, seen, str(clause, "clauseType"),
                    timelineLabel(str(clause, "clauseType"), snippet),
                    null, condition, "CLAUSE_RELATIVE_TERM", clause.get("id"),
                    clauseTitle(clause), snippet, "RELATIVE_TERM", "PLANNED");
        }

        extractDurationTerms(nodes, seen, clause, content, DURATION_TERM_PATTERN);
        extractDurationTerms(nodes, seen, clause, content, CHINESE_DURATION_TERM_PATTERN);
    }

    private void extractDurationTerms(List<Map<String, Object>> nodes, Set<String> seen,
                                      Map<String, Object> clause, String content, Pattern pattern) {
        Matcher matcher = pattern.matcher(content);
        while (matcher.find()) {
            String snippet = snippetAround(content, matcher.start(), matcher.end());
            if (!looksLikeTimelineTerm(snippet)) continue;
            String condition = matcher.group(0).replaceAll("\\s+", " ").trim();
            if (condition.length() < 2) continue;
            if (isDateFragment(condition)) continue;
            addTimelineNode(nodes, seen, str(clause, "clauseType"),
                    timelineLabel(str(clause, "clauseType"), snippet),
                    null, condition, "CLAUSE_RELATIVE_TERM", clause.get("id"),
                    clauseTitle(clause), snippet, "DURATION_TERM", "PLANNED");
        }
    }

    private boolean isDateFragment(String condition) {
        String value = condition.replaceAll("\\s+", "");
        if (value.matches(".*20\\d{2}年?$")) return true;
        if (value.matches("^(0?[1-9]|1[0-2])月$")) return true;
        if (value.matches("^(0?[1-9]|[12]\\d|3[01])日(起|内|前|后)?$")) return true;
        return value.matches("^(至|自)?(0?[1-9]|1[0-2])月(0?[1-9]|[12]\\d|3[01])日(起|内|前|后)?$");
    }

    private boolean looksLikeTimelineTerm(String snippet) {
        return snippet.contains("生效")
                || snippet.contains("到期")
                || snippet.contains("期满")
                || snippet.contains("续签")
                || snippet.contains("终止")
                || snippet.contains("解除")
                || snippet.contains("提前")
                || snippet.contains("逾期")
                || snippet.contains("超过")
                || snippet.contains("付款")
                || snippet.contains("支付")
                || snippet.contains("发票")
                || snippet.contains("交付")
                || snippet.contains("验收")
                || snippet.contains("通知")
                || snippet.contains("服务")
                || snippet.contains("完成");
    }

    private Map<String, Object> addTimelineNode(List<Map<String, Object>> nodes, Set<String> seen,
                                 String nodeType, String label, LocalDate date, String condition,
                                 String sourceType, Object sourceId, String sourceTitle,
                                 String description, String extractionMode, String status) {
        if (date == null && (condition == null || condition.isBlank())) return null;
        String key = (date == null ? "" : date.toString()) + "|" + condition + "|" + label + "|" + sourceType + "|" + sourceId;
        if (!seen.add(key)) return null;
        Map<String, Object> node = new LinkedHashMap<>();
        node.put("nodeType", nodeType == null || nodeType.isBlank() ? "OTHER" : nodeType);
        node.put("label", label == null || label.isBlank() ? "合同时间节点" : label);
        node.put("date", date == null ? null : date.toString());
        node.put("condition", condition == null || condition.isBlank() ? null : condition);
        node.put("sourceType", sourceType);
        node.put("sourceId", sourceId);
        node.put("sourceTitle", sourceTitle);
        node.put("description", description);
        node.put("extractionMode", extractionMode);
        node.put("status", status == null || status.isBlank() ? "PLANNED" : status);
        nodes.add(node);
        return node;
    }

    private String timelineLabel(String clauseType, String snippet) {
        String text = (clauseType + " " + snippet).toUpperCase(Locale.ROOT);
        if (text.contains("PAYMENT") || snippet.contains("付款") || snippet.contains("支付") || snippet.contains("发票")) return "付款/开票节点";
        if (text.contains("DELIVERY") || snippet.contains("交付") || snippet.contains("服务")) return "交付/服务节点";
        if (text.contains("ACCEPTANCE") || snippet.contains("验收")) return "验收节点";
        if (text.contains("TERMINATION") || snippet.contains("终止") || snippet.contains("解除") || snippet.contains("到期")) return "终止/到期节点";
        if (text.contains("RENEWAL") || snippet.contains("续签")) return "续签节点";
        if (text.contains("NOTICE") || snippet.contains("通知")) return "通知节点";
        return "合同时间节点";
    }

    private String clauseTitle(Map<String, Object> clause) {
        String number = str(clause, "clauseNumber");
        String title = str(clause, "title");
        if (number.isBlank()) return title;
        if (title.isBlank()) return number;
        return number + " " + title;
    }

    private String snippetAround(String content, int start, int end) {
        int left = Math.max(0, start - 48);
        int right = Math.min(content.length(), end + 72);
        return content.substring(left, right)
                .replaceAll("\\s+", " ")
                .trim();
    }

    private LocalDate safeDate(String year, String month, String day) {
        try {
            return LocalDate.of(Integer.parseInt(year),
                    Integer.parseInt(month), Integer.parseInt(day));
        } catch (Exception e) {
            return null;
        }
    }

    private LocalDate objectDate(Object value) {
        if (value == null || String.valueOf(value).isBlank()) return null;
        if (value instanceof LocalDate localDate) return localDate;
        if (value instanceof java.sql.Date sqlDate) return sqlDate.toLocalDate();
        if (value instanceof java.util.Date date) {
            return new java.sql.Date(date.getTime()).toLocalDate();
        }
        try { return LocalDate.parse(String.valueOf(value).substring(0, 10)); }
        catch (Exception e) { return null; }
    }

    private int intValue(Object value, int defaultValue) {
        if (value instanceof Number number) return number.intValue();
        try { return Integer.parseInt(String.valueOf(value)); }
        catch (Exception e) { return defaultValue; }
    }

    private String sha256(String value) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(hash);
        } catch (Exception e) {
            throw new IllegalStateException("无法计算合同内容摘要", e);
        }
    }

    private Long numberAsLong(Object value) {
        if (value instanceof Number number) return number.longValue();
        try { return Long.parseLong(String.valueOf(value)); }
        catch (Exception e) { throw new IllegalArgumentException("数据 ID 无效"); }
    }

    private Long numberAsLongOrNull(Object value) {
        if (value == null || String.valueOf(value).isBlank()) return null;
        if (value instanceof Number number) return number.longValue();
        try { return Long.parseLong(String.valueOf(value)); }
        catch (Exception e) { return null; }
    }

    private BigDecimal decimalOrNull(Object value) {
        if (value == null || String.valueOf(value).isBlank()) return null;
        try { return new BigDecimal(String.valueOf(value)); }
        catch (NumberFormatException e) { throw new IllegalArgumentException("合同金额格式错误"); }
    }

    private LocalDate dateOrNull(Object value, String fieldName) {
        if (value == null || String.valueOf(value).isBlank()) return null;
        try { return LocalDate.parse(String.valueOf(value)); }
        catch (Exception e) { throw new IllegalArgumentException(fieldName + "格式错误"); }
    }

    private String normalizeOurSide(String value) {
        String side = strValue(value).toUpperCase(Locale.ROOT);
        return switch (side) {
            case "A", "PARTY_A", "甲方" -> "A";
            case "B", "PARTY_B", "乙方" -> "B";
            default -> null;
        };
    }

    private String strValue(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }
}
