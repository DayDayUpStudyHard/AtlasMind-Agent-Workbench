package com.atlasmind.service.impl;

import com.atlasmind.agent.runtime.AgentArtifactExecutor;
import com.atlasmind.agent.runtime.AgentHarness;
import com.atlasmind.agent.runtime.AgentHarnessResult;
import com.atlasmind.agent.runtime.AgentTaskContext;
import com.atlasmind.agent.runtime.AgentTraceStore;
import com.atlasmind.gateway.AiGateway;
import com.atlasmind.gateway.GitHubIssueGateway;
import com.atlasmind.gateway.GitHubRepositoryGateway;
import com.atlasmind.entity.KbNotification;
import com.atlasmind.mapper.KbNotificationMapper;
import com.atlasmind.service.AgentActionExecutor;
import com.atlasmind.service.AgentProjectService;
import com.atlasmind.service.AgentRunExecutor;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 首个垂直闭环的实现。
 *
 * <p>分析阶段以可追溯的项目事实、知识库检索结果和结构化步骤为核心。
 * LLM 可以在后续替换报告编排器，当前实现保证没有 LLM 配置时仍能跑通状态机、
 * 引用、审批和 GitHub Issue 边界。</p>
 */
@Service
@RequiredArgsConstructor
public class AgentProjectServiceImpl implements AgentProjectService {

    private static final String SCORING_VERSION = "v1";
    private static final String ANALYSIS_MODE = "deterministic-score + llm-explanation";
    private static final List<String> RUN_TYPES = List.of(
            "HEALTH_ANALYSIS", "PROJECT_ONBOARDING", "ENGINEERING_DECISION");

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final AiGateway aiGateway;
    private final GitHubIssueGateway gitHubIssueGateway;
    private final GitHubRepositoryGateway gitHubRepositoryGateway;
    private final AgentRunExecutor agentRunExecutor;
    private final AgentActionExecutor agentActionExecutor;
    private final KbNotificationMapper notificationMapper;
    private final AgentHarness agentHarness;
    private final AgentArtifactExecutor agentArtifactExecutor;
    private final AgentTraceStore agentTraceStore;

    @Override
    public Map<String, Object> overview() {
        List<Map<String, Object>> projects = listProjects();
        Map<String, Object> data = new HashMap<>();
        data.put("projects", projects);
        data.put("projectCount", projects.size());
        data.put("activeRuns", number(jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM agent_run WHERE status IN ('CREATED','CONTEXT_BUILDING','ANALYZING','VERIFYING','PLANNING')",
                Integer.class)));
        data.put("pendingApprovals", number(jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM agent_action WHERE status='PENDING_APPROVAL'",
                Integer.class)));
        data.put("riskProjects", projects.stream()
                .filter(item -> "AT_RISK".equals(item.get("healthStatus")))
                .count());
        return data;
    }

    @Override
    public List<Map<String, Object>> listProjects() {
        List<Map<String, Object>> projects = jdbcTemplate.queryForList("""
                SELECT id, name, project_key AS projectKey, description, repository_type AS repositoryType,
                       repository_url AS repositoryUrl, default_branch AS defaultBranch,
                       business_scope AS businessScope, release_target AS releaseTarget,
                       current_milestone AS currentMilestone, team_size AS teamSize,
                       tech_stack AS techStack, health_status AS healthStatus, health_score AS healthScore,
                       last_run_id AS lastRunId, last_run_at AS lastRunAt, create_time AS createTime
                FROM agent_project
                WHERE deleted=0
                ORDER BY update_time DESC, id DESC
                """);
        for (Map<String, Object> project : projects) {
            Long id = longValue(project.get("id"));
            project.put("openRisks", number(jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM agent_action WHERE project_id=? AND status='PENDING_APPROVAL'", Integer.class, id)));
            project.put("runCount", number(jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM agent_run WHERE project_id=?", Integer.class, id)));
            project.put("evidenceCount", number(jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM project_evidence WHERE project_id=?", Integer.class, id)));
            Map<String, Object> source = firstOrNull(jdbcTemplate.queryForList("""
                    SELECT status AS syncStatus, last_sync_at AS lastSyncAt, last_error AS lastSyncError
                    FROM project_source WHERE project_id=? ORDER BY update_time DESC LIMIT 1
                    """, id));
            if (source != null) {
                project.putAll(source);
            }
            project.put("latestRun", firstOrNull(jdbcTemplate.queryForList("""
                    SELECT id, status, progress, current_step AS currentStep, create_time AS createTime
                    FROM agent_run WHERE project_id=? ORDER BY id DESC LIMIT 1
                    """, id)));
        }
        return projects;
    }

    @Override
    public Map<String, Object> getProject(Long projectId) {
        Map<String, Object> project = firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, name, project_key AS projectKey, description, repository_type AS repositoryType,
                       repository_url AS repositoryUrl, default_branch AS defaultBranch,
                       business_scope AS businessScope, release_target AS releaseTarget,
                       current_milestone AS currentMilestone, team_size AS teamSize,
                       tech_stack AS techStack, health_status AS healthStatus, health_score AS healthScore,
                       last_run_id AS lastRunId, last_run_at AS lastRunAt, create_time AS createTime
                FROM agent_project WHERE id=? AND deleted=0
                """, projectId));
        if (project == null) {
            throw new IllegalArgumentException("没有找到这个项目");
        }
        project.put("memories", jdbcTemplate.queryForList("""
                SELECT id, memory_type AS memoryType, title, content, source_type AS sourceType,
                       source_id AS sourceId, confirmed, confirmed_by AS confirmedBy,
                       create_time AS createTime, update_time AS updateTime
                FROM agent_project_memory WHERE project_id=? ORDER BY confirmed DESC, update_time DESC
                """, projectId));
        project.put("sources", jdbcTemplate.queryForList("""
                SELECT id, source_type AS sourceType, source_url AS sourceUrl, default_branch AS defaultBranch,
                       status, last_sync_job_id AS lastSyncJobId, last_sync_at AS lastSyncAt,
                       last_error AS lastError, create_time AS createTime, update_time AS updateTime
                FROM project_source WHERE project_id=? ORDER BY update_time DESC
                """, projectId));
        project.put("syncJobs", listSyncJobs(projectId));
        project.put("evidenceSummary", jdbcTemplate.queryForList("""
                SELECT object_type AS objectType, COUNT(*) AS count
                FROM project_evidence WHERE project_id=? GROUP BY object_type ORDER BY object_type
                """, projectId));
        project.put("runs", listRuns(projectId));
        project.put("reports", jdbcTemplate.queryForList("""
                SELECT id, run_id AS runId, report_type AS reportType, title, summary, health_status AS healthStatus,
                       health_score AS healthScore, dimensions_json AS dimensionsJson,
                       risks_json AS risksJson, plan_json AS planJson, citations_json AS citationsJson,
                       scoring_version AS scoringVersion, evidence_hash AS evidenceHash,
                       analysis_mode AS analysisMode, scoring_rationale_json AS scoringRationaleJson,
                       content_json AS contentJson,
                       report_markdown AS reportMarkdown, status, create_time AS createTime
                FROM agent_report WHERE project_id=? ORDER BY id DESC LIMIT 10
                """, projectId));
        return project;
    }

    @Override
    @Transactional
    public Map<String, Object> createProject(Map<String, Object> request) {
        String name = text(request, "name");
        if (name.isBlank()) {
            throw new IllegalArgumentException("项目名称不能为空");
        }
        String projectKey = text(request, "projectKey");
        if (projectKey.isBlank()) {
            projectKey = name.toUpperCase().replaceAll("[^A-Z0-9]+", "-");
        }
        Long id = insert("""
                INSERT INTO agent_project
                (name, project_key, description, repository_type, repository_url, default_branch,
                 business_scope, release_target, current_milestone, team_size, tech_stack,
                 health_status, health_score, deleted)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'UNKNOWN',0,0)
                """,
                name, projectKey, text(request, "description"),
                value(request, "repositoryType", "GITHUB"), text(request, "repositoryUrl"),
                value(request, "defaultBranch", "main"), text(request, "businessScope"),
                text(request, "releaseTarget"), text(request, "currentMilestone"),
                integerValue(request.get("teamSize")), text(request, "techStack"));
        if (!text(request, "repositoryUrl").isBlank()) {
            ensureProjectSource(id, value(request, "repositoryType", "GITHUB"),
                    text(request, "repositoryUrl"), value(request, "defaultBranch", "main"));
        }
        return getProject(id);
    }

    @Override
    public Map<String, Object> syncProjectEvidence(Long projectId) {
        Map<String, Object> project = getProject(projectId);
        String repositoryUrl = text(project, "repositoryUrl");
        if (repositoryUrl.isBlank()) {
            throw new IllegalArgumentException("同步证据前需要先配置项目仓库地址");
        }
        Long sourceId = ensureProjectSource(projectId, value(project, "repositoryType", "GITHUB"),
                repositoryUrl, value(project, "defaultBranch", "main"));
        Long jobId = insert("""
                INSERT INTO project_sync_job
                (project_id, source_id, sync_type, status, progress, message, started_at)
                VALUES (?, ?, 'MANUAL', 'RUNNING', 10, '正在连接 GitHub 只读接口', NOW())
                """, projectId, sourceId);
        jdbcTemplate.update("UPDATE project_source SET status='SYNCING', last_sync_job_id=?, last_error=NULL WHERE id=?",
                jobId, sourceId);
        try {
            List<Map<String, Object>> evidence = gitHubRepositoryGateway.collectEvidence(
                    repositoryUrl, value(project, "defaultBranch", "main"));
            Map<String, Integer> counters = storeEvidence(projectId, sourceId, evidence);
            jdbcTemplate.update("""
                    UPDATE project_sync_job SET status='DONE', progress=100, message=?,
                    counters_json=?, finished_at=NOW() WHERE id=?
                    """, "已同步 " + evidence.size() + " 条 GitHub 证据", json(counters), jobId);
            jdbcTemplate.update("""
                    UPDATE project_source SET status='READY', last_sync_job_id=?, last_sync_at=NOW(),
                    last_error=NULL WHERE id=?
                    """, jobId, sourceId);
        } catch (Exception e) {
            jdbcTemplate.update("""
                    UPDATE project_sync_job SET status='FAILED', progress=100, message='GitHub 证据同步失败',
                    error_message=?, finished_at=NOW() WHERE id=?
                    """, e.getMessage(), jobId);
            jdbcTemplate.update("""
                    UPDATE project_source SET status='FAILED', last_sync_job_id=?, last_error=? WHERE id=?
                    """, jobId, e.getMessage(), sourceId);
        }
        return firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, source_id AS sourceId, sync_type AS syncType,
                       status, progress, message, counters_json AS countersJson,
                       error_message AS errorMessage, started_at AS startedAt,
                       finished_at AS finishedAt, create_time AS createTime
                FROM project_sync_job WHERE id=?
                """, jobId));
    }

    @Override
    public List<Map<String, Object>> listProjectEvidence(Long projectId, Map<String, Object> request) {
        requireProject(projectId);
        int limit = integerValue(request.get("limit"));
        if (limit <= 0 || limit > 100) {
            limit = 30;
        }
        String objectType = text(request, "objectType");
        if (!objectType.isBlank()) {
            return jdbcTemplate.queryForList("""
                    SELECT id, project_id AS projectId, source_id AS sourceId, source_type AS sourceType,
                           object_type AS objectType, title, source_ref AS sourceRef, source_url AS sourceUrl,
                           content_snippet AS snippet, confidence_score AS confidenceScore,
                           observed_at AS observedAt, update_time AS updateTime
                    FROM project_evidence
                    WHERE project_id=? AND object_type=?
                    ORDER BY confidence_score DESC, update_time DESC
                    LIMIT ?
                    """, projectId, objectType, limit);
        }
        return jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, source_id AS sourceId, source_type AS sourceType,
                       object_type AS objectType, title, source_ref AS sourceRef, source_url AS sourceUrl,
                       content_snippet AS snippet, confidence_score AS confidenceScore,
                       observed_at AS observedAt, update_time AS updateTime
                FROM project_evidence
                WHERE project_id=?
                ORDER BY confidence_score DESC, update_time DESC
                LIMIT ?
                """, projectId, limit);
    }

    @Override
    public List<Map<String, Object>> listSyncJobs(Long projectId) {
        requireProject(projectId);
        return jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, source_id AS sourceId, sync_type AS syncType,
                       status, progress, message, counters_json AS countersJson,
                       error_message AS errorMessage, started_at AS startedAt,
                       finished_at AS finishedAt, create_time AS createTime
                FROM project_sync_job WHERE project_id=? ORDER BY id DESC LIMIT 10
                """, projectId);
    }

    @Override
    @Transactional
    public Map<String, Object> startRun(Long projectId, Map<String, Object> request) {
        requireProject(projectId);
        ensureEvidenceBeforeRun(projectId);
        String runType = value(request, "runType", "HEALTH_ANALYSIS").toUpperCase();
        if (!RUN_TYPES.contains(runType)) {
            throw new IllegalArgumentException("不支持的 Agent 任务类型：" + runType);
        }
        String question = text(request, "question");
        if (question.isBlank()) {
            question = defaultQuestion(runType);
        }
        if ("ENGINEERING_DECISION".equals(runType) && question.length() < 6) {
            throw new IllegalArgumentException("请说明需要辅助判断的研发决策问题");
        }
        Long runId = insert("""
                INSERT INTO agent_run
                (project_id, run_type, trigger_type, question, input_json, status, progress, current_step, started_at)
                VALUES (?, ?, ?, ?, ?, 'CREATED', 0, '等待 Agent 调度', NOW())
                """,
                projectId, runType, value(request, "triggerType", "MANUAL"), question, json(request));
        String[][] steps = stepsFor(runType);
        for (int i = 0; i < steps.length; i++) {
            jdbcTemplate.update("""
                    INSERT INTO agent_run_step
                    (run_id, step_order, role_name, step_name, status)
                    VALUES (?, ?, ?, ?, 'PENDING')
                    """, runId, i + 1, steps[i][0], steps[i][1]);
        }
        dispatchAfterCommit(runId);
        return getRun(runId);
    }

    @Override
    public List<Map<String, Object>> listRuns(Long projectId) {
        return jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, run_type AS runType, trigger_type AS triggerType,
                       question, input_json AS inputJson, status, progress, current_step AS currentStep, error_message AS errorMessage,
                       started_at AS startedAt, finished_at AS finishedAt, create_time AS createTime
                FROM agent_run WHERE project_id=? ORDER BY id DESC LIMIT 20
                """, projectId);
    }

    @Override
    public Map<String, Object> getRun(Long runId) {
        Map<String, Object> run = firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, run_type AS runType, trigger_type AS triggerType,
                       question, input_json AS inputJson, status, progress, current_step AS currentStep, error_message AS errorMessage,
                       started_at AS startedAt, finished_at AS finishedAt, create_time AS createTime
                FROM agent_run WHERE id=?
                """, runId));
        if (run == null) {
            throw new IllegalArgumentException("没有找到这次 Agent Run");
        }
        run.put("steps", jdbcTemplate.queryForList("""
                SELECT id, step_order AS stepOrder, role_name AS roleName, step_name AS stepName,
                       status, evidence_summary AS evidenceSummary, latency_ms AS latencyMs,
                       started_at AS startedAt, finished_at AS finishedAt, error_message AS errorMessage
                FROM agent_run_step WHERE run_id=? ORDER BY step_order
                """, runId));
        run.put("report", firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, run_id AS runId, title, summary,
                       report_type AS reportType,
                       health_status AS healthStatus, health_score AS healthScore,
                       dimensions_json AS dimensionsJson, risks_json AS risksJson,
                       plan_json AS planJson, citations_json AS citationsJson,
                       scoring_version AS scoringVersion, evidence_hash AS evidenceHash,
                       analysis_mode AS analysisMode, scoring_rationale_json AS scoringRationaleJson,
                       content_json AS contentJson,
                       report_markdown AS reportMarkdown, status, create_time AS createTime
                FROM agent_report WHERE run_id=?
                """, runId)));
        run.put("actions", jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, run_id AS runId, action_type AS actionType,
                       status, title, payload_json AS payloadJson, external_id AS externalId,
                       approved_by AS approvedBy, approved_at AS approvedAt, executed_at AS executedAt,
                       result_json AS resultJson, error_message AS errorMessage, create_time AS createTime
                FROM agent_action WHERE run_id=? ORDER BY id
                """, runId));
        run.put("toolCalls", jdbcTemplate.queryForList("""
                SELECT id, plan_step_id AS planStepId, call_id AS callId, tool_name AS toolName,
                       input_json AS inputJson, output_json AS outputJson, status,
                       latency_ms AS latencyMs, error_message AS errorMessage,
                       create_time AS createTime
                FROM agent_tool_call WHERE run_id=? ORDER BY id
                """, runId));
        run.put("traces", jdbcTemplate.queryForList("""
                SELECT id, event_type AS eventType, sequence_no AS sequenceNo, summary,
                       payload_json AS payloadJson, create_time AS createTime
                FROM agent_run_trace WHERE run_id=? ORDER BY sequence_no
                """, runId));
        return run;
    }

    @Override
    @Transactional
    public Map<String, Object> approveAction(Long runId, Long actionId, Map<String, Object> request, String approvedBy) {
        Map<String, Object> action = firstOrNull(jdbcTemplate.queryForList(
                "SELECT id FROM agent_action WHERE id=? AND run_id=?", actionId, runId));
        if (action == null) {
            throw new IllegalArgumentException("没有找到这个待执行动作");
        }
        boolean approved = booleanValue(request.get("approved"), true);
        String approver = approvedBy == null || approvedBy.isBlank() ? "authenticated-user" : approvedBy;
        jdbcTemplate.update("""
                UPDATE agent_action SET status=?, approved_by=?, approved_at=NOW(), error_message=NULL
                WHERE id=? AND run_id=?
                """, approved ? "APPROVED" : "REJECTED", approver, actionId, runId);
        if (!approved) {
            jdbcTemplate.update("UPDATE agent_run SET status='COMPLETED', progress=100, current_step='审批结束', finished_at=NOW() WHERE id=?", runId);
        } else {
            jdbcTemplate.update("UPDATE agent_run SET current_step='动作已批准，等待异步执行' WHERE id=?", runId);
            dispatchActionAfterCommit(runId, actionId);
        }
        return getRun(runId);
    }

    @Override
    @Transactional
    public Map<String, Object> executeAction(Long runId, Long actionId) {
        Map<String, Object> action = firstOrNull(jdbcTemplate.queryForList("""
                SELECT a.id, a.project_id AS projectId, a.status, a.title, a.payload_json AS payloadJson,
                       p.repository_url AS repositoryUrl
                FROM agent_action a JOIN agent_project p ON p.id=a.project_id
                WHERE a.id=? AND a.run_id=?
                """, actionId, runId));
        if (action == null) {
            throw new IllegalArgumentException("没有找到这个待执行动作");
        }
        if (!"APPROVED".equals(action.get("status"))) {
            throw new IllegalArgumentException("动作必须审批通过后才能执行");
        }
        try {
            Map<String, Object> payload = parseJson(text(action, "payloadJson"));
            Map<String, Object> result = gitHubIssueGateway.createIssue(
                    text(action, "repositoryUrl"), text(action, "title"), text(payload, "body"));
            String externalId = text(result, "number");
            jdbcTemplate.update("""
                    UPDATE agent_action SET status='EXECUTED', external_id=?, executed_at=NOW(),
                    result_json=?, error_message=NULL WHERE id=? AND run_id=?
                    """, externalId, json(result), actionId, runId);
            jdbcTemplate.update("UPDATE agent_run SET status='COMPLETED', progress=100, current_step='Issue 已创建', finished_at=NOW() WHERE id=?", runId);
        } catch (Exception e) {
            jdbcTemplate.update("""
                    UPDATE agent_action SET status='BLOCKED', error_message=? WHERE id=? AND run_id=?
                    """, e.getMessage(), actionId, runId);
        }
        return getRun(runId);
    }

    @Override
    public List<Map<String, Object>> listAllRuns() {
        return jdbcTemplate.queryForList("""
                SELECT r.id, r.project_id AS projectId, p.name AS projectName,
                       r.run_type AS runType, r.trigger_type AS triggerType,
                       r.question, r.status, r.progress, r.current_step AS currentStep,
                       r.error_message AS errorMessage, r.started_at AS startedAt,
                       r.finished_at AS finishedAt, r.create_time AS createTime
                FROM agent_run r
                JOIN agent_project p ON p.id=r.project_id
                WHERE p.deleted=0
                ORDER BY r.id DESC
                LIMIT 100
                """);
    }

    @Override
    public List<Map<String, Object>> listReports() {
        return jdbcTemplate.queryForList("""
                SELECT ar.id, ar.project_id AS projectId, p.name AS projectName,
                       ar.run_id AS runId, ar.report_type AS reportType, ar.title, ar.summary, ar.health_status AS healthStatus,
                       ar.health_score AS healthScore, ar.scoring_version AS scoringVersion,
                       ar.evidence_hash AS evidenceHash, ar.analysis_mode AS analysisMode,
                       ar.status, ar.create_time AS createTime
                FROM agent_report ar
                JOIN agent_project p ON p.id=ar.project_id
                WHERE p.deleted=0
                ORDER BY ar.id DESC
                LIMIT 100
                """);
    }

    @Override
    public List<Map<String, Object>> listActions(String status) {
        if (status == null || status.isBlank()) {
            return jdbcTemplate.queryForList("""
                    SELECT aa.id, aa.project_id AS projectId, p.name AS projectName,
                           aa.run_id AS runId, aa.action_type AS actionType, aa.status,
                           aa.title, aa.external_id AS externalId, aa.approved_by AS approvedBy,
                           aa.approved_at AS approvedAt, aa.executed_at AS executedAt,
                           aa.error_message AS errorMessage, aa.create_time AS createTime
                    FROM agent_action aa
                    JOIN agent_project p ON p.id=aa.project_id
                    WHERE p.deleted=0
                    ORDER BY aa.id DESC
                    LIMIT 100
                    """);
        }
        return jdbcTemplate.queryForList("""
                SELECT aa.id, aa.project_id AS projectId, p.name AS projectName,
                       aa.run_id AS runId, aa.action_type AS actionType, aa.status,
                       aa.title, aa.external_id AS externalId, aa.approved_by AS approvedBy,
                       aa.approved_at AS approvedAt, aa.executed_at AS executedAt,
                       aa.error_message AS errorMessage, aa.create_time AS createTime
                FROM agent_action aa
                JOIN agent_project p ON p.id=aa.project_id
                WHERE p.deleted=0 AND aa.status=?
                ORDER BY aa.id DESC
                LIMIT 100
                """, status);
    }

    @Override
    @Transactional
    public void deleteRun(Long runId) {
        Map<String, Object> run = firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, status
                FROM agent_run
                WHERE id=?
                """, runId));
        if (run == null) {
            throw new IllegalArgumentException("没有找到这次 Agent Run");
        }
        String status = text(run, "status");
        if (List.of("CREATED", "CONTEXT_BUILDING", "ANALYZING", "VERIFYING", "PLANNING").contains(status)) {
            throw new IllegalStateException("运行中的 Agent Run 不允许删除，请等待完成或失败后再处理");
        }
        Long projectId = longValue(run.get("projectId"));
        jdbcTemplate.update("DELETE FROM agent_action WHERE run_id=?", runId);
        jdbcTemplate.update("DELETE FROM agent_report WHERE run_id=?", runId);
        jdbcTemplate.update("DELETE FROM agent_project_memory WHERE source_type='AGENT_RUN' AND source_id=?",
                String.valueOf(runId));
        jdbcTemplate.update("DELETE FROM agent_tool_call WHERE run_id=?", runId);
        jdbcTemplate.update("DELETE FROM agent_run_trace WHERE run_id=?", runId);
        jdbcTemplate.update("DELETE FROM agent_run_step WHERE run_id=?", runId);
        jdbcTemplate.update("DELETE FROM agent_run WHERE id=?", runId);
        refreshProjectHealthAfterDeletion(projectId);
    }

    @Override
    @Transactional
    public void deleteReport(Long reportId) {
        Map<String, Object> report = firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, run_id AS runId
                FROM agent_report
                WHERE id=?
                """, reportId));
        if (report == null) {
            throw new IllegalArgumentException("没有找到这份报告");
        }
        Long projectId = longValue(report.get("projectId"));
        Long runId = longValue(report.get("runId"));
        jdbcTemplate.update("DELETE FROM agent_report WHERE id=?", reportId);
        jdbcTemplate.update("""
                UPDATE agent_run
                SET status='COMPLETED', progress=100, current_step='报告已由管理员删除', finished_at=IFNULL(finished_at, NOW())
                WHERE id=? AND status='WAITING_APPROVAL'
                """, runId);
        refreshProjectHealthAfterDeletion(projectId);
    }

    @Override
    @Transactional
    public void deleteAction(Long actionId) {
        Map<String, Object> action = firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, run_id AS runId, status
                FROM agent_action
                WHERE id=?
                """, actionId));
        if (action == null) {
            throw new IllegalArgumentException("没有找到这个动作");
        }
        if ("APPROVED".equals(text(action, "status"))) {
            throw new IllegalStateException("已批准且可能正在执行的动作不允许删除，请等待执行完成或阻塞后再处理");
        }
        Long projectId = longValue(action.get("projectId"));
        Long runId = longValue(action.get("runId"));
        jdbcTemplate.update("DELETE FROM agent_action WHERE id=?", actionId);
        Integer remaining = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM agent_action WHERE run_id=?",
                Integer.class,
                runId
        );
        if (number(remaining) == 0) {
            jdbcTemplate.update("""
                    UPDATE agent_run
                    SET status='COMPLETED', progress=100, current_step='动作已由管理员删除', finished_at=IFNULL(finished_at, NOW())
                    WHERE id=? AND status='WAITING_APPROVAL'
                    """, runId);
        }
        refreshProjectHealthAfterDeletion(projectId);
    }

    private void refreshProjectHealthAfterDeletion(Long projectId) {
        Map<String, Object> latest = firstOrNull(jdbcTemplate.queryForList("""
                SELECT run_id AS runId, health_status AS healthStatus, health_score AS healthScore
                FROM agent_report
                WHERE project_id=? AND report_type='HEALTH_REPORT'
                ORDER BY id DESC
                LIMIT 1
                """, projectId));
        if (latest == null) {
            jdbcTemplate.update("""
                    UPDATE agent_project
                    SET health_status='UNKNOWN', health_score=0, last_run_id=NULL, last_run_at=NULL
                    WHERE id=?
                    """, projectId);
            return;
        }
        Map<String, Object> latestRun = firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, create_time AS createTime
                FROM agent_run
                WHERE id=?
                """, latest.get("runId")));
        jdbcTemplate.update("""
                UPDATE agent_project
                SET health_status=?, health_score=?, last_run_id=?, last_run_at=?
                WHERE id=?
                """,
                value(latest, "healthStatus", "UNKNOWN"),
                integerValue(latest.get("healthScore")),
                latest.get("runId"),
                latestRun == null ? null : latestRun.get("createTime"),
                projectId);
    }

    @Override
    public void executeRun(Long runId) {
        Map<String, Object> run = getRun(runId);
        Long projectId = longValue(run.get("projectId"));
        Map<String, Object> project = getProject(projectId);
        String runType = value(run, "runType", "HEALTH_ANALYSIS");
        try {
            Map<String, Object> taskInput = parseJson(text(run, "inputJson"));
            taskInput.put("question", text(run, "question"));
            AgentHarnessResult harnessResult = agentHarness.execute(new AgentTaskContext(
                    runId, projectId, runType, text(run, "question"), project, taskInput));

            Map<String, Object> artifact;
            boolean llmArtifactFailed = harnessResult.rawArtifact().containsKey("artifactError");
            if ("HEALTH_ANALYSIS".equals(runType)) {
                if (llmArtifactFailed) {
                    artifact = buildReport(project, harnessResult.citations(), harnessResult.deterministicScoring());
                    artifact.put("analysisMode", "agent-harness + rule-based-explanation-fallback");
                } else {
                    artifact = normalizeAiReport(project, harnessResult.citations(),
                            harnessResult.rawArtifact(), harnessResult.deterministicScoring());
                    artifact.put("analysisMode", "agent-harness/" + harnessResult.executionMode());
                }
                artifact.put("reportType", "HEALTH_REPORT");
                artifact.put("content", new HashMap<>(artifact));
            } else {
                Map<String, Object> raw = llmArtifactFailed
                        ? fallbackProjectTask(runType, taskInput, project, harnessResult.citations())
                        : harnessResult.rawArtifact();
                artifact = normalizeProjectTaskArtifact(runType, taskInput, project,
                        harnessResult.citations(), raw,
                        "agent-harness/" + harnessResult.executionMode()
                                + (llmArtifactFailed ? "/artifact-fallback" : ""));
            }

            AgentArtifactExecutor.ArtifactExecutionResult persisted = agentArtifactExecutor.persistDraft(
                    projectId, runId, runType, artifact);
            completeRunSteps(runId, harnessResult);
            jdbcTemplate.update("""
                    UPDATE agent_run SET status='WAITING_APPROVAL', progress=100,
                    current_step='Agent 执行完成，等待人工审批', finished_at=NOW(), error_message=NULL
                    WHERE id=?
                    """, runId);
            agentTraceStore.trace(runId, "ARTIFACT_PERSISTED", "产物与待审批动作已持久化",
                    Map.of("reportId", persisted.reportId(), "actionId", persisted.actionId()));
            createRunNotification(runId, runTypeLabel(runType) + "已生成",
                    text(project, "name") + " 的 Agent 任务已完成，产物 #" + persisted.reportId() + " 等待审批");
        } catch (Exception e) {
            jdbcTemplate.update("""
                    UPDATE agent_run SET status='FAILED', progress=100, current_step='运行失败',
                    error_message=?, finished_at=NOW() WHERE id=?
                    """, e.getMessage(), runId);
            createRunNotification(runId, "项目健康分析失败",
                    text(project, "name") + " 的异步健康分析失败：" + safeMessage(e));
        }
    }

    private void completeRunSteps(Long runId, AgentHarnessResult result) {
        String evidence = "计划 " + mapList(result.plan().get("steps")).size()
                + " 步；工具观察 " + result.observations().size()
                + " 条；引用 " + result.citations().size()
                + " 条；执行模式 " + result.executionMode();
        jdbcTemplate.update("""
                UPDATE agent_run_step
                SET status='DONE', evidence_summary=?, started_at=IFNULL(started_at, NOW()),
                    finished_at=NOW(), latency_ms=TIMESTAMPDIFF(MICROSECOND, IFNULL(started_at, NOW()), NOW()) / 1000
                WHERE run_id=?
                """, evidence, runId);
    }

    private Map<String, Object> normalizeProjectTaskArtifact(String runType, Map<String, Object> taskInput,
                                                              Map<String, Object> project,
                                                              List<Map<String, Object>> citations,
                                                              Map<String, Object> raw,
                                                              String analysisMode) {
        Map<String, Object> result = raw;
        if (raw.get("data") instanceof Map<?, ?> data) {
            Map<String, Object> normalized = new HashMap<>();
            data.forEach((key, value) -> normalized.put(String.valueOf(key), value));
            result = normalized;
        }
        List<Map<String, Object>> reportCitations = normalizeCitations(result.get("citations"), citations);
        if (reportCitations.isEmpty()) {
            reportCitations = citations.stream().limit(10).toList();
        }
        List<Map<String, Object>> risks = normalizeRisks(result.get("risks"), citations);
        List<Map<String, Object>> plan = normalizePlan(result.get("plan"), citations);
        Map<String, Object> content = new HashMap<>(result);
        content.put("sections", normalizeSections(result.get("sections"), citations));
        content.put("criteria", normalizeCriteria(result.get("criteria"), citations));
        content.put("options", normalizeOptions(result.get("options"), citations));
        content.put("risks", risks);
        content.put("plan", plan);
        content.put("citations", reportCitations);
        content.put("taskInput", taskInput);

        String title = value(result, "title", text(project, "name") + " " + runTypeLabel(runType));
        String summary = value(result, "summary", "已基于当前可用证据生成草稿，待确认项请由项目负责人补充。");
        String markdown = renderProjectTaskMarkdown(runType, title, summary, content, reportCitations);
        Map<String, Object> artifact = new HashMap<>();
        artifact.put("reportType", "PROJECT_ONBOARDING".equals(runType) ? "ONBOARDING_GUIDE" : "DECISION_MEMO");
        artifact.put("title", title);
        artifact.put("summary", summary);
        artifact.put("risks", risks);
        artifact.put("plan", plan);
        artifact.put("citations", reportCitations);
        artifact.put("content", content);
        artifact.put("evidenceHash", evidenceSnapshotHash(project, citations));
        artifact.put("analysisMode", analysisMode);
        artifact.put("reportMarkdown", markdown);
        artifact.put("issueTitle", "PROJECT_ONBOARDING".equals(runType)
                ? "[AtlasMind 入职] " + text(project, "name") + " 首周接手任务"
                : "[AtlasMind 决策验证] " + abbreviate(text(taskInput, "question"), 120));
        return artifact;
    }

    private List<Map<String, Object>> normalizeSections(Object value, List<Map<String, Object>> citations) {
        List<Map<String, Object>> sections = new ArrayList<>();
        for (Map<String, Object> section : mapList(value)) {
            String title = text(section, "title");
            if (title.isBlank()) continue;
            List<Map<String, Object>> items = new ArrayList<>();
            for (Map<String, Object> item : mapList(section.get("items"))) {
                String itemTitle = text(item, "title");
                if (itemTitle.isBlank()) continue;
                Map<String, Object> citation = resolveCitation(item.get("citationSourceId"), citations);
                String description = value(item, "description", "待确认");
                if (citation == null && !description.contains("待确认")) description += "（依据待确认）";
                Map<String, Object> normalized = new HashMap<>();
                normalized.put("title", itemTitle);
                normalized.put("description", description);
                normalized.put("citation", citation);
                items.add(normalized);
            }
            sections.add(Map.of("title", title, "items", items));
        }
        return sections;
    }

    private List<Map<String, Object>> normalizeCriteria(Object value, List<Map<String, Object>> citations) {
        List<Map<String, Object>> criteria = new ArrayList<>();
        for (Map<String, Object> item : mapList(value)) {
            String name = text(item, "name");
            if (name.isBlank()) continue;
            Map<String, Object> normalized = new HashMap<>();
            normalized.put("name", name);
            normalized.put("importance", value(item, "importance", "MEDIUM"));
            normalized.put("reason", value(item, "reason", "判断依据待确认"));
            normalized.put("citation", resolveCitation(item.get("citationSourceId"), citations));
            criteria.add(normalized);
        }
        return criteria;
    }

    private List<Map<String, Object>> normalizeOptions(Object value, List<Map<String, Object>> citations) {
        List<Map<String, Object>> options = new ArrayList<>();
        for (Map<String, Object> item : mapList(value)) {
            String name = text(item, "name");
            if (name.isBlank()) continue;
            List<Map<String, Object>> optionCitations = new ArrayList<>();
            for (String sourceId : stringList(item.get("citationSourceIds"))) {
                Map<String, Object> citation = resolveCitation(sourceId, citations);
                if (citation != null) optionCitations.add(citation);
            }
            Map<String, Object> normalized = new HashMap<>();
            normalized.put("name", name);
            normalized.put("verdict", value(item, "verdict", "待评估"));
            normalized.put("benefits", stringList(item.get("benefits")));
            normalized.put("costs", stringList(item.get("costs")));
            normalized.put("risks", stringList(item.get("risks")));
            normalized.put("citations", optionCitations);
            options.add(normalized);
        }
        return options;
    }

    private List<String> stringList(Object value) {
        List<String> values = new ArrayList<>();
        if (value instanceof List<?> list) {
            for (Object item : list) {
                if (item != null && !String.valueOf(item).isBlank()) values.add(String.valueOf(item));
            }
        }
        return values;
    }

    private String renderProjectTaskMarkdown(String runType, String title, String summary,
                                              Map<String, Object> content,
                                              List<Map<String, Object>> citations) {
        StringBuilder markdown = new StringBuilder();
        markdown.append("# ").append(title).append("\n\n")
                .append("> 产物类型：**").append(runTypeLabel(runType))
                .append("** | 事实来源：GitHub 项目证据 + 项目绑定知识库\n\n")
                .append("## 摘要\n\n").append(summary).append("\n\n");
        if ("PROJECT_ONBOARDING".equals(runType)) {
            for (Map<String, Object> section : mapList(content.get("sections"))) {
                markdown.append("## ").append(text(section, "title")).append("\n\n");
                for (Map<String, Object> item : mapList(section.get("items"))) {
                    markdown.append("- **").append(text(item, "title")).append("**：")
                            .append(text(item, "description"))
                            .append(citationSuffix(item.get("citation"))).append("\n");
                }
                markdown.append('\n');
            }
            appendPlanMarkdown(markdown, "首周接手计划", mapList(content.get("plan")));
        } else {
            markdown.append("## 建议结论\n\n")
                    .append(value(content, "recommendation", "建议先补齐证据并进行小范围验证。"))
                    .append("\n\n> 证据置信度：**")
                    .append(value(content, "confidence", "LOW")).append("**\n\n")
                    .append("## 决策标准\n\n");
            for (Map<String, Object> criterion : mapList(content.get("criteria"))) {
                markdown.append("- **").append(text(criterion, "name")).append("**（")
                        .append(value(criterion, "importance", "MEDIUM")).append("）：")
                        .append(text(criterion, "reason"))
                        .append(citationSuffix(criterion.get("citation"))).append("\n");
            }
            markdown.append("\n## 方案比较\n\n");
            for (Map<String, Object> option : mapList(content.get("options"))) {
                markdown.append("### ").append(text(option, "name")).append("\n\n")
                        .append(text(option, "verdict")).append("\n\n");
                appendStringItems(markdown, "收益", stringList(option.get("benefits")));
                appendStringItems(markdown, "成本", stringList(option.get("costs")));
                appendStringItems(markdown, "风险", stringList(option.get("risks")));
            }
            appendPlanMarkdown(markdown, "决策验证计划", mapList(content.get("plan")));
        }
        List<Map<String, Object>> risks = mapList(content.get("risks"));
        if (!risks.isEmpty()) {
            markdown.append("\n## 需要关注的风险\n\n");
            for (Map<String, Object> risk : risks) {
                markdown.append("- [").append(text(risk, "severity")).append("] **")
                        .append(text(risk, "title")).append("**：")
                        .append(text(risk, "description"))
                        .append(citationSuffix(risk.get("citation"))).append("\n");
            }
        }
        markdown.append("\n## 引用来源\n\n");
        for (Map<String, Object> citation : citations) {
            markdown.append("- [").append(value(citation, "objectType", "EVIDENCE")).append("] ")
                    .append(text(citation, "title")).append(" | ")
                    .append(text(citation, "sourceRef")).append("\n");
        }
        markdown.append("\n> 本产物只使用当前可用项目证据。标记为待确认的内容必须由项目成员补充后才能作为事实。\n");
        if ("ENGINEERING_DECISION".equals(runType)) {
            markdown.append("> Agent 提供决策支持，最终选择与执行责任仍由人工审批者承担。\n");
        }
        return markdown.toString();
    }

    private void appendPlanMarkdown(StringBuilder markdown, String title, List<Map<String, Object>> plan) {
        markdown.append("\n## ").append(title).append("\n\n");
        for (Map<String, Object> item : plan) {
            markdown.append("- ").append(value(item, "id", "P"))
                    .append(" **").append(text(item, "title")).append("**（负责人：")
                    .append(value(item, "ownerRole", "项目负责人")).append("；验收：")
                    .append(text(item, "acceptance")).append("）")
                    .append(citationSuffix(item.get("citation"))).append("\n");
        }
    }

    private void appendStringItems(StringBuilder markdown, String label, List<String> values) {
        if (!values.isEmpty()) {
            markdown.append("- ").append(label).append("：").append(String.join("；", values)).append("\n");
        }
    }

    private String citationSuffix(Object value) {
        if (value instanceof Map<?, ?> map) {
            Object title = map.get("title");
            if (title != null && !String.valueOf(title).isBlank()) {
                return " [来源：" + title + "]";
            }
        }
        return "";
    }

    private Map<String, Object> fallbackProjectTask(String runType, Map<String, Object> taskInput,
                                                     Map<String, Object> project,
                                                     List<Map<String, Object>> citations) {
        String sourceId = citations.isEmpty() ? "" : text(citations.get(0), "sourceId");
        if ("PROJECT_ONBOARDING".equals(runType)) {
            return Map.of(
                    "title", text(project, "name") + " 项目接手与入职手册",
                    "summary", "结构化模型暂不可用，当前手册按已同步项目事实生成；启动命令、模块负责人和环境权限仍需人工确认。",
                    "sections", List.of(
                            Map.of("title", "项目定位", "items", List.of(Map.of(
                                    "title", "业务与当前里程碑",
                                    "description", value(project, "businessScope", "业务范围待确认") + "；当前里程碑："
                                            + value(project, "currentMilestone", "待确认"),
                                    "citationSourceId", sourceId))),
                            Map.of("title", "技术入口", "items", List.of(Map.of(
                                    "title", "技术栈与代码入口",
                                    "description", value(project, "techStack", "技术栈待确认")
                                            + "。请从 README、构建配置和目录证据继续核验本地启动方式。",
                                    "citationSourceId", sourceId))),
                            Map.of("title", "信息缺口", "items", List.of(Map.of(
                                    "title", "需要项目成员补充",
                                    "description", "环境权限、模块负责人、发布流程、故障联系人和首个可独立交付任务均待确认。",
                                    "citationSourceId", "")))
                    ),
                    "risks", List.of(Map.of("id", "R-01", "title", "关键接手信息不完整", "severity", "MEDIUM",
                            "description", "缺少的信息必须由项目负责人确认，不能根据通用经验补造。", "citationSourceId", "")),
                    "plan", List.of(
                            Map.of("id", "P1", "title", "跑通本地环境与测试", "ownerRole", value(taskInput, "audience", "新成员"),
                                    "acceptance", "记录可复现的启动步骤和测试结果；无法确认的权限单独列出。", "citationSourceId", sourceId),
                            Map.of("id", "P2", "title", "完成核心模块走读", "ownerRole", "项目负责人 + 新成员",
                                    "acceptance", "确认核心模块职责、关键依赖和一条主要业务流程。", "citationSourceId", sourceId),
                            Map.of("id", "P3", "title", "完成首个小范围交付", "ownerRole", value(taskInput, "audience", "新成员"),
                                    "acceptance", "提交一个通过项目现有检查流程的低风险改动。", "citationSourceId", "")
                    ),
                    "citations", citations.stream().limit(8).map(item -> Map.of("sourceId", text(item, "sourceId"))).toList()
            );
        }
        String question = value(taskInput, "question", "研发方案选择");
        return Map.of(
                "title", text(project, "name") + " 研发决策备忘录",
                "summary", "结构化模型暂不可用，当前备忘录只给出保守的验证路径，不对缺失的成本和效果数据作推断。",
                "recommendation", "针对“" + question + "”，建议先设计可回滚的小范围验证，再依据项目实测结果作最终选择。",
                "confidence", "LOW",
                "criteria", List.of(
                        Map.of("name", "与现有技术栈兼容性", "importance", "HIGH", "reason", "应基于仓库配置和真实集成结果判断。", "citationSourceId", sourceId),
                        Map.of("name", "交付与回滚成本", "importance", "HIGH", "reason", "当前缺少实测数据，待验证。", "citationSourceId", "")
                ),
                "options", List.of(
                        Map.of("name", "小范围验证后推进", "verdict", "推荐作为下一步",
                                "benefits", List.of("用项目实测数据降低决策不确定性", "保留回滚空间"),
                                "costs", List.of("需要额外验证时间"), "risks", List.of("验证范围不当可能产生偏差"),
                                "citationSourceIds", sourceId.isBlank() ? List.of() : List.of(sourceId)),
                        Map.of("name", "维持现状", "verdict", "可作为短期对照方案",
                                "benefits", List.of("不引入即时迁移风险"), "costs", List.of("问题可能继续存在"),
                                "risks", List.of("缺少变化收益"), "citationSourceIds", List.of())
                ),
                "risks", List.of(Map.of("id", "R-01", "title", "决策证据不足", "severity", "HIGH",
                        "description", "缺少项目级基准、迁移成本或约束证据，结论置信度较低。", "citationSourceId", "")),
                "plan", List.of(
                        Map.of("id", "P1", "title", "定义决策指标与约束", "ownerRole", "技术负责人",
                                "acceptance", "形成可量化的成功指标、不可突破约束和回滚条件。", "citationSourceId", sourceId),
                        Map.of("id", "P2", "title", "执行小范围技术验证", "ownerRole", "研发负责人",
                                "acceptance", "记录两种方案在同一场景下的结果与成本。", "citationSourceId", ""),
                        Map.of("id", "P3", "title", "召开人工决策评审", "ownerRole", "项目负责人",
                                "acceptance", "依据验证证据确认选择、责任人和实施计划。", "citationSourceId", "")
                ),
                "citations", citations.stream().limit(8).map(item -> Map.of("sourceId", text(item, "sourceId"))).toList()
        );
    }

    private String defaultQuestion(String runType) {
        return switch (runType) {
            case "PROJECT_ONBOARDING" -> "为新加入项目的研发成员生成项目接手手册和首周计划";
            case "ENGINEERING_DECISION" -> "评估当前研发决策的可选方案、权衡和验证计划";
            default -> "分析项目健康状态、关键风险和下一阶段交付计划";
        };
    }

    private String[][] stepsFor(String runType) {
        return switch (runType) {
            case "PROJECT_ONBOARDING" -> new String[][]{
                    {"上下文构建 Agent", "理解接手目标与新成员角色"},
                    {"证据检索 Agent", "检索代码、文档与工程规范"},
                    {"项目导览 Agent", "梳理模块、启动方式与关键流程"},
                    {"证据复核 Agent", "核验事实并标记信息缺口"},
                    {"入职规划 Agent", "生成首周接手计划"},
                    {"手册生成 Agent", "生成可审计接手手册"}
            };
            case "ENGINEERING_DECISION" -> new String[][]{
                    {"决策建模 Agent", "理解决策问题与约束"},
                    {"证据检索 Agent", "检索项目事实与工程规范"},
                    {"方案分析 Agent", "比较备选方案与权衡"},
                    {"反思验证 Agent", "检查假设、引用与信息缺口"},
                    {"验证规划 Agent", "生成低风险验证计划"},
                    {"备忘录生成 Agent", "生成可审计决策备忘录"}
            };
            default -> new String[][]{
                    {"上下文构建 Agent", "构建项目上下文"},
                    {"证据检索 Agent", "检索项目证据"},
                    {"项目分析 Agent", "分析五个健康维度"},
                    {"证据复核 Agent", "核验结论和引用来源"},
                    {"交付规划 Agent", "生成交付计划"},
                    {"报告生成 Agent", "生成可审计报告"}
            };
        };
    }

    private String runTypeLabel(String runType) {
        return switch (runType) {
            case "PROJECT_ONBOARDING" -> "项目接手手册";
            case "ENGINEERING_DECISION" -> "研发决策备忘录";
            default -> "项目健康分析";
        };
    }

    private String abbreviate(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) return value == null ? "" : value;
        return value.substring(0, Math.max(1, maxLength - 1)) + "…";
    }

    private void createRunNotification(Long runId, String title, String content) {
        try {
            KbNotification notification = new KbNotification();
            notification.setType(title.endsWith("失败") ? "AGENT_RUN_FAILED" : "AGENT_RUN_COMPLETED");
            notification.setTitle(title);
            notification.setContent(content);
            notification.setRelatedType("AGENT_RUN");
            notification.setRelatedId(runId);
            notification.setReadStatus(0);
            notificationMapper.insert(notification);
        } catch (Exception ignored) {
            // A notification failure must not change the Agent Run result.
        }
    }

    private String safeMessage(Exception exception) {
        String message = exception.getMessage();
        return message == null || message.isBlank() ? exception.getClass().getSimpleName() : message;
    }

    private List<Map<String, Object>> retrieveEvidence(Map<String, Object> project) {
        List<Map<String, Object>> citations = new ArrayList<>();
        Long projectId = longValue(project.get("id"));
        List<Map<String, Object>> evidenceRows = listProjectEvidence(projectId, Map.of("limit", 6));
        for (int i = 0; i < evidenceRows.size(); i++) {
            Map<String, Object> row = evidenceRows.get(i);
            Map<String, Object> item = new HashMap<>();
            item.put("sourceType", text(row, "sourceType"));
            item.put("objectType", text(row, "objectType"));
            item.put("sourceId", text(row, "id"));
            item.put("sourceRef", text(row, "sourceRef"));
            item.put("sourceUrl", text(row, "sourceUrl"));
            item.put("title", text(row, "title"));
            item.put("snippet", text(row, "snippet"));
            item.put("score", row.get("confidenceScore"));
            item.put("rank", i + 1);
            citations.add(item);
        }
        if (!citations.isEmpty()) {
            citations.addAll(retrieveBoundKnowledge(project, 4));
            return citations;
        }
        citations.addAll(retrieveBoundKnowledge(project, 8));
        if (!citations.isEmpty()) {
            return citations;
        }
        try {
            Map<String, Object> result = aiGateway.testRetrieval(Map.of(
                    "message", "项目健康分析 " + text(project, "name") + " " + text(project, "description"),
                    "topK", 5
            ));
            Object hits = result.get("hits");
            if (hits instanceof List<?> list) {
                for (Object hit : list) {
                    if (hit instanceof Map<?, ?> map) {
                        Map<String, Object> item = new HashMap<>();
                        map.forEach((key, value) -> item.put(String.valueOf(key), value));
                        citations.add(item);
                    }
                }
            }
        } catch (Exception ignored) {
            // A missing Python/ES service is represented as an explicit unknown, not a fake citation.
        }
        if (citations.isEmpty()) {
                citations.add(Map.of(
                    "sourceType", "PROJECT_CONTEXT",
                    "sourceId", text(project, "id"),
                    "title", "项目录入事实",
                    "snippet", text(project, "description"),
                    "score", 1.0,
                    "rank", 1
            ));
        }
        return citations;
    }

    private List<Map<String, Object>> retrieveBoundKnowledge(Map<String, Object> project, int remainingSlots) {
        if (remainingSlots <= 0) {
            return List.of();
        }
        Long projectId = longValue(project.get("id"));
        List<Map<String, Object>> documents = jdbcTemplate.queryForList("""
                SELECT d.id, d.title, s.name AS spaceName
                FROM project_kb_document pkd
                JOIN kb_document d ON d.id=pkd.document_id
                JOIN kb_space s ON s.id=d.space_id
                WHERE pkd.project_id=?
                  AND d.deleted=0
                  AND d.status='READY'
                  AND s.deleted=0
                  AND s.enabled=1
                ORDER BY pkd.create_time DESC, d.update_time DESC
                LIMIT 6
                """, projectId);
        List<Map<String, Object>> results = new ArrayList<>();
        for (Map<String, Object> document : documents) {
            if (results.size() >= remainingSlots) break;
            try {
                Map<String, Object> result = aiGateway.testRetrieval(Map.of(
                        "message", "项目健康分析 " + text(project, "name") + " " + text(project, "description")
                                + " " + text(project, "techStack") + " " + text(project, "currentMilestone"),
                        "documentId", document.get("id"),
                        "topK", Math.min(3, remainingSlots - results.size())
                ));
                Object hits = result.get("hits");
                if (hits instanceof List<?> list) {
                    for (Object hit : list) {
                        if (results.size() >= remainingSlots) break;
                        if (hit instanceof Map<?, ?> map) {
                            Map<String, Object> item = new HashMap<>();
                            map.forEach((key, value) -> item.put(String.valueOf(key), value));
                            item.put("sourceType", "DOCUMENT");
                            item.put("objectType", "KB_DOCUMENT");
                            item.put("sourceId", String.valueOf(document.get("id")));
                            item.put("sourceRef", document.get("spaceName") + " / " + document.get("title"));
                            item.put("title", value(item, "title", text(document, "title")));
                            item.put("rank", results.size() + 1);
                            results.add(item);
                        }
                    }
                }
            } catch (Exception ignored) {
                // Bound documents are first-class context, but a retrieval outage should not fake citations.
            }
        }
        return results;
    }

    private void ensureEvidenceBeforeRun(Long projectId) {
        Map<String, Object> project = getProject(projectId);
        if (text(project, "repositoryUrl").isBlank()) {
            return;
        }
        Integer evidenceCount = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM project_evidence WHERE project_id=?",
                Integer.class,
                projectId
        );
        if (evidenceCount != null && evidenceCount > 0) {
            return;
        }
        throw new IllegalStateException("项目已绑定 GitHub，但还没有同步到证据；请先完成 GitHub 证据同步后再运行健康分析");
    }

    private Map<String, Object> scoreProject(Map<String, Object> project, List<Map<String, Object>> citations) {
        Map<String, Integer> counts = countCitations(citations);
        String evidenceText = normalizedEvidenceText(project, citations);
        boolean hasGithubEvidence = citations.stream().anyMatch(item -> "GITHUB".equals(text(item, "sourceType")));
        boolean hasReadme = counts.getOrDefault("README", 0) > 0;
        boolean hasFileTree = counts.getOrDefault("FILE_TREE", 0) > 0;
        boolean hasFile = counts.getOrDefault("FILE", 0) > 0;
        boolean hasCommit = counts.getOrDefault("COMMIT", 0) > 0;
        boolean hasIssue = counts.getOrDefault("ISSUE", 0) > 0;
        boolean hasPr = counts.getOrDefault("PR", 0) > 0;
        boolean hasDependencyConfig = containsAny(evidenceText, "pom.xml", "package.json", "pyproject.toml",
                "build.gradle", "requirements.txt", "pnpm-lock", "yarn.lock", "package-lock");
        boolean hasTests = containsAny(evidenceText, "test", "tests", "pytest", "junit", "vitest", "jest",
                "coverage", "单元测试", "测试");
        boolean hasCi = containsAny(evidenceText, ".github/workflows", "github actions", "ci.yml", "ci.yaml",
                "jenkins", "gitlab-ci", "pipeline", "流水线", "持续集成");
        boolean hasMilestone = !text(project, "currentMilestone").isBlank();
        boolean hasReleaseTarget = !text(project, "releaseTarget").isBlank();
        boolean hasTechStack = !text(project, "techStack").isBlank();
        boolean hasTeam = integerValue(project.get("teamSize")) > 0;

        List<Map<String, Object>> rationale = new ArrayList<>();
        int delivery = 45
                + signal(rationale, "交付进展", hasIssue || hasPr, 25, "Issue/PR 数据", "已同步 Issue 或 PR，可判断交付边界", "缺少 Issue/PR，交付阻塞只能待确认")
                + signal(rationale, "交付进展", hasMilestone, 15, "当前里程碑", "项目已记录当前里程碑", "缺少当前里程碑")
                + signal(rationale, "交付进展", hasReleaseTarget, 10, "目标版本", "项目已记录目标版本", "缺少目标版本或发布时间窗口")
                + signal(rationale, "交付进展", hasCommit, 5, "近期提交", "已同步提交记录", "缺少近期提交证据");
        int quality = 35
                + signal(rationale, "工程质量", hasTests, 25, "测试证据", "检测到测试相关文件或描述", "缺少测试目录、测试框架或覆盖率证据")
                + signal(rationale, "工程质量", hasCi, 25, "CI/CD 证据", "检测到持续集成或流水线线索", "缺少 CI/CD 构建结果或流水线配置")
                + signal(rationale, "工程质量", hasDependencyConfig, 10, "依赖配置", "检测到依赖或构建配置", "缺少依赖/构建配置证据")
                + signal(rationale, "工程质量", hasPr, 5, "PR 评审", "已同步 PR 证据", "缺少 PR 评审证据");
        int architecture = 45
                + signal(rationale, "架构可维护性", hasReadme, 15, "README", "已同步 README，可支撑基础理解", "缺少 README 或 README 未被同步")
                + signal(rationale, "架构可维护性", hasFileTree, 15, "目录结构", "已同步根目录文件树", "缺少目录结构证据")
                + signal(rationale, "架构可维护性", hasDependencyConfig, 15, "构建配置", "检测到构建/依赖配置", "缺少构建/依赖配置")
                + signal(rationale, "架构可维护性", hasTechStack, 10, "技术栈", "项目已记录技术栈", "缺少技术栈描述");
        int risk = 45
                + signal(rationale, "风险暴露", hasGithubEvidence, 15, "真实仓库证据", "已同步 GitHub 可引用事实", "缺少真实仓库证据")
                + signal(rationale, "风险暴露", hasCi, 10, "构建信号", "存在 CI/CD 线索", "构建稳定性未知")
                + signal(rationale, "风险暴露", hasTests, 10, "质量信号", "存在测试线索", "测试覆盖未知")
                + signal(rationale, "风险暴露", hasIssue || hasPr, 10, "协作风险信号", "存在 Issue/PR 线索", "需求、缺陷和阻塞项未知")
                + signal(rationale, "风险暴露", hasReadme || hasFile, 10, "代码/文档证据", "存在文件或文档证据", "代码和文档证据不足");
        int collaboration = 40
                + signal(rationale, "协作活跃度", hasCommit, 25, "提交活跃", "已同步提交记录", "缺少提交活跃度证据")
                + signal(rationale, "协作活跃度", hasPr, 20, "PR 协作", "已同步 PR 证据", "缺少 PR 协作证据")
                + signal(rationale, "协作活跃度", hasIssue, 10, "Issue 协作", "已同步 Issue 证据", "缺少 Issue 协作证据")
                + signal(rationale, "协作活跃度", hasTeam, 5, "团队规模", "已记录团队规模", "缺少团队规模");

        List<Map<String, Object>> dimensions = List.of(
                scoredDimension("交付进展", delivery, 25, "Issue/PR、里程碑、目标版本和提交活跃度共同决定。"),
                scoredDimension("工程质量", quality, 25, "测试、CI/CD、依赖配置和 PR 评审证据共同决定。"),
                scoredDimension("架构可维护性", architecture, 20, "README、目录结构、构建配置和技术栈描述共同决定。"),
                scoredDimension("风险暴露", risk, 15, "真实仓库、构建、测试、协作和代码文档证据共同决定。"),
                scoredDimension("协作活跃度", collaboration, 15, "Commit、PR、Issue 和团队规模共同决定。")
        );
        int score = (int) Math.round(
                delivery * 0.25 + quality * 0.25 + architecture * 0.20 + risk * 0.15 + collaboration * 0.15
        );
        score = clampScore(score);
        String evidenceHash = evidenceSnapshotHash(project, citations);
        Map<String, Object> previousSameSnapshot = firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, health_score AS healthScore, create_time AS createTime
                FROM agent_report
                WHERE project_id=? AND evidence_hash=?
                ORDER BY id DESC
                LIMIT 1
                """, project.get("id"), evidenceHash));
        Map<String, Object> scoring = new HashMap<>();
        scoring.put("healthScore", score);
        scoring.put("healthStatus", score >= 80 ? "HEALTHY" : score >= 65 ? "WATCH" : "AT_RISK");
        scoring.put("dimensions", dimensions);
        scoring.put("rationale", rationale);
        scoring.put("scoringVersion", SCORING_VERSION);
        scoring.put("evidenceHash", evidenceHash);
        scoring.put("analysisMode", ANALYSIS_MODE);
        scoring.put("snapshotReused", previousSameSnapshot != null);
        if (previousSameSnapshot != null) {
            scoring.put("previousReportId", previousSameSnapshot.get("id"));
            scoring.put("previousHealthScore", previousSameSnapshot.get("healthScore"));
        }
        return scoring;
    }

    private int signal(List<Map<String, Object>> rationale, String dimension, boolean present, int points,
                       String title, String positiveNote, String missingNote) {
        Map<String, Object> item = new HashMap<>();
        item.put("dimension", dimension);
        item.put("title", title);
        item.put("type", present ? "POSITIVE" : "MISSING");
        item.put("impact", present ? points : -points);
        item.put("note", present ? positiveNote : missingNote);
        rationale.add(item);
        return present ? points : 0;
    }

    private Map<String, Object> scoredDimension(String name, int score, int weight, String basis) {
        Map<String, Object> item = new HashMap<>();
        int normalizedScore = clampScore(score);
        item.put("name", name);
        item.put("score", normalizedScore);
        item.put("weight", weight);
        item.put("note", basis + " 当前规则评分为 " + normalizedScore + "/100。");
        return item;
    }

    private int clampScore(int score) {
        return Math.max(0, Math.min(100, score));
    }

    private boolean containsAny(String value, String... keywords) {
        for (String keyword : keywords) {
            if (value.contains(keyword.toLowerCase())) {
                return true;
            }
        }
        return false;
    }

    private String normalizedEvidenceText(Map<String, Object> project, List<Map<String, Object>> citations) {
        StringBuilder builder = new StringBuilder();
        builder.append(text(project, "description")).append('\n')
                .append(text(project, "businessScope")).append('\n')
                .append(text(project, "currentMilestone")).append('\n')
                .append(text(project, "releaseTarget")).append('\n')
                .append(text(project, "techStack")).append('\n');
        for (Map<String, Object> item : citations) {
            builder.append(text(item, "objectType")).append('\n')
                    .append(text(item, "title")).append('\n')
                    .append(text(item, "sourceRef")).append('\n')
                    .append(text(item, "snippet")).append('\n');
        }
        return builder.toString().toLowerCase();
    }

    private String evidenceSnapshotHash(Map<String, Object> project, List<Map<String, Object>> citations) {
        StringBuilder builder = new StringBuilder();
        builder.append("project:").append(text(project, "id")).append('\n')
                .append("repo:").append(text(project, "repositoryUrl")).append('\n')
                .append("milestone:").append(text(project, "currentMilestone")).append('\n')
                .append("release:").append(text(project, "releaseTarget")).append('\n');
        citations.stream()
                .map(item -> text(item, "sourceType") + "|" + text(item, "objectType") + "|"
                        + text(item, "sourceId") + "|" + text(item, "sourceRef") + "|"
                        + text(item, "title") + "|" + text(item, "snippet"))
                .sorted()
                .forEach(value -> builder.append(value).append('\n'));
        return sha256(builder.toString());
    }

    private Map<String, Object> normalizeAiReport(Map<String, Object> project,
                                                   List<Map<String, Object>> citations,
                                                   Map<String, Object> raw,
                                                   Map<String, Object> scoring) {
        Map<String, Object> result = raw;
        if (raw.get("data") instanceof Map<?, ?> data) {
            Map<String, Object> normalized = new HashMap<>();
            data.forEach((key, value) -> normalized.put(String.valueOf(key), value));
            result = normalized;
        }

        List<Map<String, Object>> dimensions = mapList(scoring.get("dimensions"));
        List<Map<String, Object>> risks = normalizeRisks(result.get("risks"), citations);
        List<Map<String, Object>> plan = normalizePlan(result.get("plan"), citations);
        if (plan.size() < 3) {
            throw new IllegalArgumentException("结构化项目分析缺少交付计划");
        }

        int score = integerValue(scoring.get("healthScore"));
        String status = text(scoring, "healthStatus");
        List<Map<String, Object>> reportCitations = normalizeCitations(result.get("citations"), citations);
        if (reportCitations.isEmpty()) {
            reportCitations = citations.stream().limit(8).toList();
        }
        String title = value(result, "title", text(project, "name") + " 项目健康与交付计划");
        String summary = value(result, "summary", "LLM 未提供项目摘要，结论需要人工复核。");
        String markdown = renderAiReportMarkdown(title, status, score, summary, dimensions, risks, plan,
                reportCitations, scoring);

        Map<String, Object> report = new HashMap<>();
        report.put("title", title);
        report.put("summary", summary);
        report.put("healthStatus", status);
        report.put("healthScore", score);
        report.put("dimensions", dimensions);
        report.put("risks", risks);
        report.put("plan", plan);
        report.put("citations", reportCitations);
        report.put("reportMarkdown", markdown);
        report.put("issueTitle", "[AtlasMind] " + text(project, "name") + " 交付跟进");
        report.put("issueBody", markdown);
        report.put("analysisSource", "LLM_EXPLANATION");
        report.put("scoringVersion", scoring.get("scoringVersion"));
        report.put("evidenceHash", scoring.get("evidenceHash"));
        report.put("analysisMode", scoring.get("analysisMode"));
        report.put("scoringRationale", scoring.get("rationale"));
        return report;
    }

    private List<Map<String, Object>> normalizeDimensions(Object value) {
        List<Map<String, Object>> normalized = new ArrayList<>();
        for (Map<String, Object> item : mapList(value)) {
            String name = text(item, "name");
            if (name.isBlank()) {
                continue;
            }
            Map<String, Object> dimension = new HashMap<>();
            dimension.put("name", name);
            dimension.put("score", Math.max(0, Math.min(100, integerValue(item.get("score")))));
            dimension.put("note", value(item, "note", "证据不足，待确认。"));
            normalized.add(dimension);
        }
        return normalized;
    }

    private List<Map<String, Object>> normalizeRisks(Object value, List<Map<String, Object>> citations) {
        List<Map<String, Object>> normalized = new ArrayList<>();
        int index = 1;
        for (Map<String, Object> item : mapList(value)) {
            String title = text(item, "title");
            if (title.isBlank()) {
                continue;
            }
            String severity = text(item, "severity").toUpperCase();
            if ("高".equals(severity)) severity = "HIGH";
            if ("中".equals(severity)) severity = "MEDIUM";
            if ("低".equals(severity)) severity = "LOW";
            if (!List.of("HIGH", "MEDIUM", "LOW").contains(severity)) severity = "MEDIUM";
            Map<String, Object> risk = new HashMap<>();
            risk.put("id", value(item, "id", "R-" + String.format("%02d", index++)));
            risk.put("title", title);
            risk.put("severity", severity);
            String description = value(item, "description", "风险描述待补充。");
            Map<String, Object> citation = resolveCitation(item.get("citationSourceId"), citations);
            if (citation == null && !description.contains("待确认")) {
                description += "（直接证据待确认）";
            }
            risk.put("description", description);
            risk.put("citation", citation);
            normalized.add(risk);
        }
        return normalized;
    }

    private List<Map<String, Object>> normalizePlan(Object value, List<Map<String, Object>> citations) {
        List<Map<String, Object>> normalized = new ArrayList<>();
        int index = 1;
        for (Map<String, Object> item : mapList(value)) {
            String title = text(item, "title");
            if (title.isBlank()) {
                continue;
            }
            Map<String, Object> task = new HashMap<>();
            task.put("id", value(item, "id", "P" + index++));
            task.put("title", title);
            task.put("ownerRole", value(item, "ownerRole", "项目负责人"));
            task.put("dependency", value(item, "dependency", "无"));
            String acceptance = value(item, "acceptance", "完成后由项目负责人确认结果。");
            if (resolveCitation(item.get("citationSourceId"), citations) == null && !acceptance.contains("待确认")) {
                acceptance += "（依据待确认）";
            }
            task.put("acceptance", acceptance);
            task.put("riskId", text(item, "riskId"));
            task.put("citation", resolveCitation(item.get("citationSourceId"), citations));
            normalized.add(task);
        }
        return normalized;
    }

    private List<Map<String, Object>> normalizeCitations(Object value, List<Map<String, Object>> citations) {
        List<Map<String, Object>> normalized = new ArrayList<>();
        for (Map<String, Object> item : mapList(value)) {
            Map<String, Object> citation = resolveCitation(item.get("sourceId"), citations);
            if (citation != null && normalized.stream().noneMatch(existing ->
                    text(existing, "sourceId").equals(text(citation, "sourceId")))) {
                normalized.add(citation);
            }
        }
        return normalized;
    }

    private Map<String, Object> resolveCitation(Object candidate, List<Map<String, Object>> citations) {
        String sourceId;
        if (candidate instanceof Map<?, ?> map) {
            Object value = map.get("sourceId");
            if (value == null) value = map.get("id");
            sourceId = value == null ? "" : String.valueOf(value);
        } else {
            sourceId = candidate == null ? "" : String.valueOf(candidate);
        }
        if (sourceId.isBlank()) {
            return null;
        }
        String lookupId = sourceId;
        return citations.stream()
                .filter(item -> lookupId.equals(text(item, "sourceId")) || lookupId.equals(text(item, "sourceRef")))
                .findFirst()
                .orElse(null);
    }

    private List<Map<String, Object>> mapList(Object value) {
        List<Map<String, Object>> result = new ArrayList<>();
        if (value instanceof List<?> list) {
            for (Object item : list) {
                if (item instanceof Map<?, ?> map) {
                    Map<String, Object> normalized = new HashMap<>();
                    map.forEach((key, itemValue) -> normalized.put(String.valueOf(key), itemValue));
                    result.add(normalized);
                }
            }
        }
        return result;
    }

    private String renderAiReportMarkdown(String title, String status, int score, String summary,
                                          List<Map<String, Object>> dimensions,
                                          List<Map<String, Object>> risks,
                                          List<Map<String, Object>> plan,
                                          List<Map<String, Object>> citations,
                                          Map<String, Object> scoring) {
        StringBuilder markdown = new StringBuilder();
        markdown.append("# ").append(title).append("\n\n")
                .append("> 健康状态：**").append(healthStatusLabel(status)).append("** | 评分：**")
                .append(score).append("/100** | 评分方式：规则评分器 ").append(scoring.get("scoringVersion"))
                .append(" | 解释生成：DeepSeek\n\n")
                .append("## 摘要\n\n").append(summary).append("\n\n")
                .append("## 五个健康维度\n\n");
        for (Map<String, Object> item : dimensions) {
            markdown.append("- ").append(text(item, "name")).append("：")
                    .append(item.get("score")).append("/100")
                    .append("（权重 ").append(item.get("weight")).append("%） | ")
                    .append(text(item, "note")).append("\n");
        }
        markdown.append("\n## 评分依据\n\n");
        for (Map<String, Object> item : mapList(scoring.get("rationale"))) {
            markdown.append("- ").append(text(item, "dimension")).append(" / ")
                    .append(text(item, "title")).append("：")
                    .append("POSITIVE".equals(text(item, "type")) ? "+" : "")
                    .append(item.get("impact")).append("，")
                    .append(text(item, "note")).append("\n");
        }
        markdown.append("\n## 关键风险\n\n");
        for (Map<String, Object> item : risks) {
            markdown.append("- [").append(text(item, "severity")).append("] ")
                    .append(text(item, "title")).append("：").append(text(item, "description")).append("\n");
        }
        markdown.append("\n## 下一阶段交付计划\n\n");
        for (Map<String, Object> item : plan) {
            markdown.append("- ").append(text(item, "id")).append(" ")
                    .append(text(item, "title")).append("（负责人：")
                    .append(text(item, "ownerRole")).append("；验收：")
                    .append(text(item, "acceptance")).append("）\n");
        }
        markdown.append("\n## 引用来源\n\n");
        for (Map<String, Object> item : citations) {
            markdown.append("- [").append(value(item, "objectType", "EVIDENCE")).append("] ")
                    .append(text(item, "title")).append(" | ").append(text(item, "sourceRef")).append("\n");
        }
        markdown.append("\n> evidenceHash: `").append(scoring.get("evidenceHash")).append("`\n");
        if (booleanValue(scoring.get("snapshotReused"), false)) {
            markdown.append("> 本次证据快照与报告 #").append(scoring.get("previousReportId"))
                    .append(" 一致，健康分沿用同一套规则评分结果；解释文本可重新生成。\n");
        }
        markdown.append("> 健康分由确定性规则评分器计算；DeepSeek 只负责解释、风险描述和计划建议。缺少直接证据的内容已标记为待确认。\n");
        return markdown.toString();
    }

    private Map<String, Object> buildReport(Map<String, Object> project, List<Map<String, Object>> citations,
                                            Map<String, Object> scoring) {
        Map<String, Integer> evidenceCounts = countCitations(citations);
        int repoFacts = evidenceCounts.values().stream().mapToInt(Integer::intValue).sum();
        boolean hasGithubEvidence = repoFacts > 0 && citations.stream()
                .anyMatch(item -> "GITHUB".equals(text(item, "sourceType")));
        boolean hasIssueEvidence = evidenceCounts.getOrDefault("ISSUE", 0) > 0;
        boolean hasPullRequestEvidence = evidenceCounts.getOrDefault("PR", 0) > 0;
        boolean hasCommitEvidence = evidenceCounts.getOrDefault("COMMIT", 0) > 0;
        boolean hasFileEvidence = evidenceCounts.getOrDefault("README", 0) > 0
                || evidenceCounts.getOrDefault("FILE", 0) > 0
                || evidenceCounts.getOrDefault("FILE_TREE", 0) > 0;
        List<Map<String, Object>> dimensions = mapList(scoring.get("dimensions"));
        int score = integerValue(scoring.get("healthScore"));
        String status = text(scoring, "healthStatus");
        List<Map<String, Object>> risks = List.of(
                risk("R-01", hasIssueEvidence || hasPullRequestEvidence ? "交付事项需要进一步分流" : "交付证据不完整",
                        "中",
                        hasIssueEvidence || hasPullRequestEvidence
                                ? "已存在 Issue/PR 证据，应将其整理进下一阶段交付边界和负责人列表。"
                                : "当前报告缺少实时 Issue、PR 和 CI 数据，无法完整判断交付阻塞。",
                        citations.get(0)),
                risk("R-02", hasFileEvidence ? "技术债需要代码级跟进" : "关键技术债需要补证",
                        "中",
                        hasFileEvidence
                                ? "已具备部分仓库文档或构建文件证据，但仍需要依赖扫描、测试覆盖和模块级分析。"
                                : "需要补充仓库结构、依赖和测试扫描证据后再形成结论。",
                        citations.get(0)),
                risk("R-03", "发布目标缺少验收边界", "低", "建议补充 Definition of Done、里程碑验收标准和风险退出条件。", Map.of(
                        "sourceType", "PROJECT_CONTEXT", "sourceId", text(project, "id"),
                        "title", "项目录入事实", "snippet", text(project, "releaseTarget")
                ))
        );
        List<Map<String, Object>> plan = List.of(
                task("P1", hasGithubEvidence ? "将已同步 GitHub 证据分流为交付风险" : "同步仓库目录、README、Issue 和 PR", "仓库分析 Agent", "R-01",
                        hasGithubEvidence ? "把有证据支撑的风险映射到负责人和下一里程碑。" : "补齐可引用的代码事实和协作事实。"),
                task("P2", "补充技术债、依赖和测试扫描", "项目分析 Agent", "R-02", "产出模块、依赖、测试覆盖和构建稳定性证据。"),
                task("P3", "确认下一里程碑验收标准", "交付规划 Agent", "R-03", "将报告建议转为可执行的交付边界和验收条件。")
        );
        String title = text(project, "name") + " 项目健康与交付计划";
        String statusLabel = healthStatusLabel(status);
        String summary = "当前项目健康状态为「" + statusLabel + "」，评分 " + score + "/100。证据复核 Agent 检查了 "
                + repoFacts + " 条可引用事实；缺少证据支撑的结论已标记为待确认。";
        String markdown = renderAiReportMarkdown(title, status, score, summary, dimensions, risks, plan,
                citations.stream().limit(8).toList(), scoring);
        Map<String, Object> report = new HashMap<>();
        report.put("title", title);
        report.put("summary", summary);
        report.put("healthStatus", status);
        report.put("healthScore", score);
        report.put("dimensions", dimensions);
        report.put("risks", risks);
        report.put("plan", plan);
        report.put("citations", citations);
        report.put("reportMarkdown", markdown);
        report.put("issueTitle", "[AtlasMind] " + text(project, "name") + " 交付跟进");
        report.put("issueBody", markdown);
        report.put("scoringVersion", scoring.get("scoringVersion"));
        report.put("evidenceHash", scoring.get("evidenceHash"));
        report.put("analysisMode", "deterministic-score + rule-based-explanation");
        report.put("scoringRationale", scoring.get("rationale"));
        return report;
    }

    private String healthStatusLabel(String status) {
        return switch (status) {
            case "HEALTHY" -> "稳定";
            case "WATCH" -> "关注";
            case "AT_RISK" -> "有风险";
            default -> "未分析";
        };
    }

    private void advance(Long runId, String status, int progress, String currentStep,
                         int stepOrder, String stepStatus, String evidence) {
        jdbcTemplate.update("""
                UPDATE agent_run SET status=?, progress=?, current_step=?,
                started_at=IFNULL(started_at, NOW()) WHERE id=?
                """, status, progress, currentStep, runId);
        jdbcTemplate.update("""
                UPDATE agent_run_step SET status=?, evidence_summary=?, started_at=IFNULL(started_at, NOW()),
                finished_at=NOW() WHERE run_id=? AND step_order=?
                """, stepStatus, evidence, runId, stepOrder);
        if ("WAITING_APPROVAL".equals(status)) {
            Map<String, Object> run = firstOrNull(jdbcTemplate.queryForList("""
                    SELECT p.name AS projectName, p.health_score AS healthScore, ar.run_type AS runType
                    FROM agent_run ar JOIN agent_project p ON p.id=ar.project_id
                    WHERE ar.id=?
                    """, runId));
            if (run != null) {
                String runType = value(run, "runType", "HEALTH_ANALYSIS");
                if ("HEALTH_ANALYSIS".equals(runType)) {
                    createRunNotification(runId, "项目健康分析完成",
                            text(run, "projectName") + " 的异步健康分析已完成，健康评分 "
                                    + value(run, "healthScore", "待确认") + "/100。请打开项目查看报告和交付计划。");
                } else {
                    String label = runTypeLabel(runType);
                    createRunNotification(runId, label + "已生成",
                            text(run, "projectName") + " 的" + label + "已生成。请打开项目查看证据、结论和待审批后续动作。");
                }
            }
        }
    }

    private void requireProject(Long projectId) {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM agent_project WHERE id=? AND deleted=0", Integer.class, projectId);
        if (number(count) == 0) {
            throw new IllegalArgumentException("没有找到这个项目");
        }
    }

    private void dispatchAfterCommit(Long runId) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            agentRunExecutor.execute(runId);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                agentRunExecutor.execute(runId);
            }
        });
    }

    private void dispatchActionAfterCommit(Long runId, Long actionId) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            agentActionExecutor.execute(runId, actionId);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                agentActionExecutor.execute(runId, actionId);
            }
        });
    }

    private Long insert(String sql, Object... params) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement statement = connection.prepareStatement(sql, Statement.RETURN_GENERATED_KEYS);
            for (int i = 0; i < params.length; i++) {
                statement.setObject(i + 1, params[i]);
            }
            return statement;
        }, keyHolder);
        return keyHolder.getKey().longValue();
    }

    private Map<String, Object> dimension(String name, int score, String note) {
        return Map.of("name", name, "score", score, "note", note);
    }

    private Map<String, Object> risk(String id, String title, String severity, String description, Map<String, Object> citation) {
        return Map.of("id", id, "title", title, "severity", severity, "description", description, "citation", citation);
    }

    private Map<String, Object> task(String id, String title, String ownerRole, String dependency, String acceptance) {
        return Map.of("id", id, "title", title, "ownerRole", ownerRole, "dependency", dependency, "acceptance", acceptance);
    }

    private Long ensureProjectSource(Long projectId, String sourceType, String sourceUrl, String defaultBranch) {
        Map<String, Object> existing = firstOrNull(jdbcTemplate.queryForList("""
                SELECT id FROM project_source WHERE project_id=? AND source_url=?
                """, projectId, sourceUrl));
        if (existing != null) {
            jdbcTemplate.update("""
                    UPDATE project_source SET source_type=?, default_branch=? WHERE id=?
                    """, sourceType, defaultBranch, existing.get("id"));
            return longValue(existing.get("id"));
        }
        return insert("""
                INSERT INTO project_source
                (project_id, source_type, source_url, default_branch, status)
                VALUES (?, ?, ?, ?, 'PENDING')
                """, projectId, sourceType, sourceUrl, defaultBranch);
    }

    private Map<String, Integer> storeEvidence(Long projectId, Long sourceId, List<Map<String, Object>> evidence) {
        Map<String, Integer> counters = new HashMap<>();
        for (Map<String, Object> item : evidence) {
            String objectType = value(item, "objectType", "UNKNOWN");
            String title = value(item, "title", objectType);
            String sourceRef = text(item, "sourceRef");
            String sourceUrl = text(item, "sourceUrl");
            String snippet = text(item, "snippet");
            String hash = sha256(objectType + "\n" + title + "\n" + sourceRef + "\n" + sourceUrl + "\n" + snippet);
            jdbcTemplate.update("""
                    INSERT INTO project_evidence
                    (project_id, source_id, source_type, object_type, title, source_ref, source_url,
                     content_snippet, raw_json, evidence_hash, confidence_score, observed_at)
                    VALUES (?, ?, 'GITHUB', ?, ?, ?, ?, ?, ?, ?, ?, NOW())
                    ON DUPLICATE KEY UPDATE
                        source_id=VALUES(source_id),
                        title=VALUES(title),
                        source_ref=VALUES(source_ref),
                        source_url=VALUES(source_url),
                        content_snippet=VALUES(content_snippet),
                        raw_json=VALUES(raw_json),
                        confidence_score=VALUES(confidence_score),
                        observed_at=NOW()
                    """, projectId, sourceId, objectType, title, sourceRef, sourceUrl,
                    snippet, json(item.get("raw")), hash, item.getOrDefault("confidenceScore", 0.8));
            counters.put(objectType, counters.getOrDefault(objectType, 0) + 1);
        }
        return counters;
    }

    private Map<String, Integer> countCitations(List<Map<String, Object>> citations) {
        Map<String, Integer> counters = new HashMap<>();
        for (Map<String, Object> citation : citations) {
            String type = value(citation, "objectType", value(citation, "sourceType", "UNKNOWN"));
            counters.put(type, counters.getOrDefault(type, 0) + 1);
        }
        return counters;
    }

    private Map<String, Object> parseJson(String value) {
        try {
            return objectMapper.readValue(value, new TypeReference<>() {});
        } catch (Exception e) {
            return Map.of();
        }
    }

    private String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder();
            for (byte item : bytes) {
                builder.append(String.format("%02x", item));
            }
            return builder.toString();
        } catch (Exception e) {
            throw new IllegalStateException(e.getMessage(), e);
        }
    }

    private String json(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            return "{}";
        }
    }

    private Map<String, Object> firstOrNull(List<Map<String, Object>> rows) {
        return rows == null || rows.isEmpty() ? null : rows.get(0);
    }

    private String text(Map<String, Object> map, String key) {
        Object value = map == null ? null : map.get(key);
        return value == null ? "" : String.valueOf(value);
    }

    private String value(Map<String, Object> map, String key, String fallback) {
        String value = text(map, key);
        return value.isBlank() ? fallback : value;
    }

    private Integer integerValue(Object value) {
        if (value instanceof Number number) return number.intValue();
        try {
            return value == null ? 0 : Integer.valueOf(String.valueOf(value));
        } catch (NumberFormatException ignored) {
            return 0;
        }
    }

    private Long longValue(Object value) {
        if (value instanceof Number number) return number.longValue();
        try {
            return value == null ? null : Long.valueOf(String.valueOf(value));
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private int number(Number value) {
        return value == null ? 0 : value.intValue();
    }

    private boolean booleanValue(Object value, boolean fallback) {
        return value == null ? fallback : Boolean.parseBoolean(String.valueOf(value));
    }
}
