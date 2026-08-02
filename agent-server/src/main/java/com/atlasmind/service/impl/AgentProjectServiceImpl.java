package com.atlasmind.service.impl;

import com.atlasmind.config.SystemConfigRepository;
import com.atlasmind.gateway.AiGateway;
import com.atlasmind.gateway.GitHubIssueGateway;
import com.atlasmind.gateway.GitHubRepositoryGateway;
import com.atlasmind.service.AgentActionExecutor;
import com.atlasmind.service.AgentProjectService;
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
import java.util.UUID;

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

    private static final List<String> RUN_TYPES = List.of(
            "HEALTH_ANALYSIS", "PROJECT_ONBOARDING", "ENGINEERING_DECISION");

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final AiGateway aiGateway;
    private final GitHubIssueGateway gitHubIssueGateway;
    private final GitHubRepositoryGateway gitHubRepositoryGateway;
    private final AgentActionExecutor agentActionExecutor;
    private final SystemConfigRepository systemConfigRepo;

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
    public Map<String, Object> organizationOverview() {
        Map<String, Object> data = new HashMap<>();

        // Health distribution across all projects
        List<Map<String, Object>> healthDist = jdbcTemplate.queryForList("""
                SELECT health_status AS status, COUNT(*) AS count
                FROM agent_project WHERE deleted=0
                GROUP BY health_status
                """);
        data.put("healthDistribution", healthDist);

        // Trend: last 4 health reports with scores
        List<Map<String, Object>> trends = jdbcTemplate.queryForList("""
                SELECT p.id AS projectId, p.name, r.health_score AS healthScore,
                       r.health_status AS healthStatus, r.create_time AS createTime
                FROM agent_report r
                JOIN agent_project p ON p.id=r.project_id AND p.deleted=0
                WHERE r.report_type='HEALTH_REPORT'
                ORDER BY r.create_time DESC
                LIMIT 40
                """);
        data.put("recentReports", trends);

        // Common risks across projects (same risk title appearing in >=2 projects)
        List<Map<String, Object>> commonRisks = jdbcTemplate.queryForList("""
                SELECT risks_json AS risksJson, p.name AS projectName, p.id AS projectId
                FROM agent_report r
                JOIN agent_project p ON p.id=r.project_id AND p.deleted=0
                WHERE r.report_type='HEALTH_REPORT'
                  AND r.risks_json IS NOT NULL
                ORDER BY r.create_time DESC
                LIMIT 100
                """);

        List<Map<String, Object>> commonRiskList = new ArrayList<>();
        Map<String, List<String>> riskToProjects = new java.util.LinkedHashMap<>();
        for (Map<String, Object> row : commonRisks) {
            String risksJson = text(row, "risksJson");
            if (risksJson.isEmpty()) continue;
            List<Map<String, Object>> risks = parseJsonArray(risksJson);
            if (risks == null || risks.isEmpty()) continue;
            String projectName = text(row, "projectName");
            for (Map<String, Object> risk : risks) {
                String title = text(risk, "title");
                if (!title.isBlank()) {
                    riskToProjects.computeIfAbsent(title, k -> new ArrayList<>()).add(projectName);
                }
            }
        }
        for (var entry : riskToProjects.entrySet()) {
            List<String> projects = entry.getValue();
            if (projects.size() >= 2) {
                Map<String, Object> item = new HashMap<>();
                item.put("riskTitle", entry.getKey());
                item.put("affectedProjects", projects);
                item.put("affectedCount", projects.size());
                commonRiskList.add(item);
            }
        }
        data.put("commonRisks", commonRiskList);

        // Active runs count
        data.put("activeRuns", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM agent_run WHERE status IN " +
                "('CREATED','CONTEXT_BUILDING','ANALYZING','VERIFYING','PLANNING')",
                Integer.class));

        // Pending approvals count
        data.put("pendingApprovals", jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM agent_action WHERE status='PENDING_APPROVAL'",
                Integer.class));

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
    public Map<String, Object> getMemory(Long memoryId) {
        Map<String, Object> memory = firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, memory_type AS memoryType,
                       title, content, source_type AS sourceType, source_id AS sourceId,
                       confirmed, confirmed_by AS confirmedBy,
                       create_time AS createTime, update_time AS updateTime
                FROM agent_project_memory WHERE id=?
                """, memoryId));
        if (memory == null) {
            throw new IllegalArgumentException("未找到该记忆记录");
        }
        return memory;
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
                SELECT id, memory_type AS memoryType, title,
                       LEFT(content, 200) AS content, source_type AS sourceType,
                       source_id AS sourceId, confirmed, confirmed_by AS confirmedBy,
                       create_time AS createTime, update_time AS updateTime
                FROM agent_project_memory WHERE project_id=?
                ORDER BY confirmed DESC, update_time DESC
                LIMIT 20
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
        project.put("runs", jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, run_type AS runType, trigger_type AS triggerType,
                       question, status, progress, current_step AS currentStep, error_message AS errorMessage,
                       started_at AS startedAt, finished_at AS finishedAt, create_time AS createTime
                FROM agent_run WHERE project_id=? ORDER BY id DESC LIMIT 5
                """, projectId));
        project.put("reports", jdbcTemplate.queryForList("""
                SELECT id, run_id AS runId, report_type AS reportType, title, summary,
                       health_status AS healthStatus, health_score AS healthScore,
                       scoring_version AS scoringVersion, evidence_hash AS evidenceHash,
                       analysis_mode AS analysisMode, status, create_time AS createTime
                FROM agent_report WHERE project_id=? ORDER BY id DESC LIMIT 5
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
                SELECT a.id, a.project_id AS projectId, a.action_type AS actionType,
                       a.status, a.title, a.payload_json AS payloadJson,
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
        String actionType = text(action, "actionType");
        try {
            Map<String, Object> payload = parseJson(text(action, "payloadJson"));
            Map<String, Object> result = null;
            String externalId = null;
            String completedStep = "动作已执行";

            switch (actionType) {
                case "CREATE_GITHUB_ISSUE" -> {
                    String body = text(payload, "body");
                    if (body.isBlank()) {
                        body = text(payload, "description");
                    }
                    result = gitHubIssueGateway.createIssue(
                            text(action, "repositoryUrl"),
                            text(action, "title"), body);
                    externalId = text(result, "number");
                    completedStep = "GitHub Issue 已创建";
                }
                case "CREATE_GITHUB_MILESTONE" -> {
                    result = gitHubIssueGateway.createMilestone(
                            text(action, "repositoryUrl"),
                            text(action, "title"),
                            text(payload, "description"),
                            text(payload, "dueOn"));
                    externalId = text(result, "number");
                    completedStep = "GitHub Milestone 已创建";
                }
                case "UPDATE_PROJECT_CONFIG" -> {
                    String key = text(payload, "key");
                    String value = text(payload, "value");
                    if (key.isBlank()) {
                        throw new IllegalArgumentException("UPDATE_PROJECT_CONFIG 缺少 key");
                    }
                    // Whitelist of allowed config keys
                    if (!java.util.Set.of("currentMilestone", "releaseTarget",
                            "teamSize", "businessScope").contains(key)) {
                        throw new IllegalArgumentException("不支持的配置项: " + key);
                    }
                    jdbcTemplate.update(
                            "UPDATE agent_project SET " + key + "=? WHERE id=?",
                            value, action.get("projectId"));
                    result = Map.of("updated", true, "key", key, "value", value);
                    completedStep = "项目配置已更新";
                }
                default -> throw new IllegalArgumentException(
                        "不支持的动作类型: " + actionType);
            }

            jdbcTemplate.update("""
                    UPDATE agent_action SET status='EXECUTED', external_id=?,
                    executed_at=NOW(), result_json=?, error_message=NULL
                    WHERE id=? AND run_id=?
                    """, externalId, json(result), actionId, runId);
            jdbcTemplate.update("""
                    UPDATE agent_run SET status='COMPLETED', progress=100,
                    current_step=?, finished_at=NOW() WHERE id=?
                    """, completedStep, runId);
        } catch (Exception e) {
            jdbcTemplate.update("""
                    UPDATE agent_action SET status='BLOCKED', error_message=?
                    WHERE id=? AND run_id=?
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
    private void requireProject(Long projectId) {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM agent_project WHERE id=? AND deleted=0", Integer.class, projectId);
        if (number(count) == 0) {
            throw new IllegalArgumentException("没有找到这个项目");
        }
    }

    private void dispatchAfterCommit(Long runId) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            dispatchToPython(runId);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                dispatchToPython(runId);
            }
        });
    }

    /**
     * Delegate Agent run execution to the Python Runtime via {@code POST /internal/agent/run}.
     */
    private void dispatchToPython(Long runId) {
        try {
            aiGateway.startAgentRun(buildRunPayload(runId));
        } catch (Exception e) {
            markRunFailed(runId, "Python agent runtime unavailable: " + e.getMessage());
        }
    }

    private void markRunFailed(Long runId, String errorMessage) {
        jdbcTemplate.update("""
                UPDATE agent_run
                SET status='FAILED', progress=0,
                    current_step='Agent 服务不可用，请稍后重试',
                    error_message=?, finished_at=NOW()
                WHERE id=?
                """, errorMessage, runId);
    }

    /**
     * Build the JSON payload that Python {@code POST /internal/agent/run} expects.
     */
    private Map<String, Object> buildRunPayload(Long runId) {
        Map<String, Object> run = getRun(runId);
        Map<String, Object> project = jdbcTemplate.queryForMap("""
                SELECT id, name, description, business_scope AS businessScope,
                       release_target AS releaseTarget, current_milestone AS currentMilestone,
                       team_size AS teamSize, tech_stack AS techStack,
                       repository_type AS repositoryType, repository_url AS repositoryUrl,
                       health_status AS healthStatus, health_score AS healthScore
                FROM agent_project WHERE id=?
                """, run.get("projectId"));

        Map<String, Object> payload = new HashMap<>();
        payload.put("requestId", UUID.randomUUID().toString());
        payload.put("runId", runId);
        payload.put("projectId", run.get("projectId"));
        payload.put("taskType", run.get("runType"));
        payload.put("question", run.getOrDefault("question", ""));
        payload.put("actor", "java-service");
        payload.put("project", project);

        String inputJson = (String) run.get("inputJson");
        payload.put("taskInput", inputJson == null || inputJson.isBlank()
                ? Map.of() : parseJsonMap(inputJson));
        payload.put("options", Map.of());
        return payload;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> parseJsonArray(String json) {
        try {
            return objectMapper.readValue(json, List.class);
        } catch (Exception e) {
            return List.of();
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseJsonMap(String json) {
        try {
            return objectMapper.readValue(json, Map.class);
        } catch (Exception e) {
            return Map.of();
        }
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
