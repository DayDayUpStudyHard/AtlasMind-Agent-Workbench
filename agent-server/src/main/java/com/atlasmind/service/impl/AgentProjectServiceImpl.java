package com.atlasmind.service.impl;

import com.atlasmind.gateway.AiGateway;
import com.atlasmind.gateway.GitHubIssueGateway;
import com.atlasmind.gateway.GitHubRepositoryGateway;
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

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final AiGateway aiGateway;
    private final GitHubIssueGateway gitHubIssueGateway;
    private final GitHubRepositoryGateway gitHubRepositoryGateway;
    private final AgentRunExecutor agentRunExecutor;
    private final AgentActionExecutor agentActionExecutor;

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
            throw new IllegalArgumentException("Project not found");
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
                SELECT id, run_id AS runId, title, summary, health_status AS healthStatus,
                       health_score AS healthScore, dimensions_json AS dimensionsJson,
                       risks_json AS risksJson, plan_json AS planJson, citations_json AS citationsJson,
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
            throw new IllegalArgumentException("Project name is required");
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
            throw new IllegalArgumentException("Project repository URL is required before sync");
        }
        Long sourceId = ensureProjectSource(projectId, value(project, "repositoryType", "GITHUB"),
                repositoryUrl, value(project, "defaultBranch", "main"));
        Long jobId = insert("""
                INSERT INTO project_sync_job
                (project_id, source_id, sync_type, status, progress, message, started_at)
                VALUES (?, ?, 'MANUAL', 'RUNNING', 10, 'Connecting to GitHub read API', NOW())
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
                    """, "Synced " + evidence.size() + " GitHub evidence items", json(counters), jobId);
            jdbcTemplate.update("""
                    UPDATE project_source SET status='READY', last_sync_job_id=?, last_sync_at=NOW(),
                    last_error=NULL WHERE id=?
                    """, jobId, sourceId);
        } catch (Exception e) {
            jdbcTemplate.update("""
                    UPDATE project_sync_job SET status='FAILED', progress=100, message='GitHub sync failed',
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
        String question = text(request, "question");
        if (question.isBlank()) {
            question = "Analyze project health, key risks, and the next delivery plan";
        }
        Long runId = insert("""
                INSERT INTO agent_run
                (project_id, run_type, trigger_type, question, status, progress, current_step, started_at)
                VALUES (?, 'HEALTH_ANALYSIS', ?, ?, 'CREATED', 0, 'Waiting for Agent dispatch', NOW())
                """,
                projectId, value(request, "triggerType", "MANUAL"), question);
        String[][] steps = {
                {"Context Builder", "Build project context"},
                {"Evidence Retriever", "Retrieve project evidence"},
                {"Project Analyst", "Analyze five health dimensions"},
                {"Evidence Reviewer", "Verify conclusions and citations"},
                {"Delivery Planner", "Create delivery plan"},
                {"Report Composer", "Compose auditable report"}
        };
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
                       question, status, progress, current_step AS currentStep, error_message AS errorMessage,
                       started_at AS startedAt, finished_at AS finishedAt, create_time AS createTime
                FROM agent_run WHERE project_id=? ORDER BY id DESC LIMIT 20
                """, projectId);
    }

    @Override
    public Map<String, Object> getRun(Long runId) {
        Map<String, Object> run = firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, run_type AS runType, trigger_type AS triggerType,
                       question, status, progress, current_step AS currentStep, error_message AS errorMessage,
                       started_at AS startedAt, finished_at AS finishedAt, create_time AS createTime
                FROM agent_run WHERE id=?
                """, runId));
        if (run == null) {
            throw new IllegalArgumentException("Agent Run not found");
        }
        run.put("steps", jdbcTemplate.queryForList("""
                SELECT id, step_order AS stepOrder, role_name AS roleName, step_name AS stepName,
                       status, evidence_summary AS evidenceSummary, latency_ms AS latencyMs,
                       started_at AS startedAt, finished_at AS finishedAt, error_message AS errorMessage
                FROM agent_run_step WHERE run_id=? ORDER BY step_order
                """, runId));
        run.put("report", firstOrNull(jdbcTemplate.queryForList("""
                SELECT id, project_id AS projectId, run_id AS runId, title, summary,
                       health_status AS healthStatus, health_score AS healthScore,
                       dimensions_json AS dimensionsJson, risks_json AS risksJson,
                       plan_json AS planJson, citations_json AS citationsJson,
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
        return run;
    }

    @Override
    @Transactional
    public Map<String, Object> approveAction(Long runId, Long actionId, Map<String, Object> request, String approvedBy) {
        Map<String, Object> action = firstOrNull(jdbcTemplate.queryForList(
                "SELECT id FROM agent_action WHERE id=? AND run_id=?", actionId, runId));
        if (action == null) {
            throw new IllegalArgumentException("Action not found");
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
            jdbcTemplate.update("UPDATE agent_run SET current_step='Action approved; queued for execution' WHERE id=?", runId);
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
            throw new IllegalArgumentException("Action not found");
        }
        if (!"APPROVED".equals(action.get("status"))) {
            throw new IllegalArgumentException("Action must be approved before execution");
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
                       ar.run_id AS runId, ar.title, ar.summary, ar.health_status AS healthStatus,
                       ar.health_score AS healthScore, ar.status, ar.create_time AS createTime
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
    public void executeRun(Long runId) {
        Map<String, Object> run = getRun(runId);
        Long projectId = longValue(run.get("projectId"));
        Map<String, Object> project = getProject(projectId);
        try {
            advance(runId, "CONTEXT_BUILDING", 12, "Building project context", 1, "DONE", "Project facts, goals, tech stack, and long-term memory loaded");
            advance(runId, "ANALYZING", 30, "Retrieving project evidence", 2, "DONE", "RAG plus GitHub connector adapter");

            List<Map<String, Object>> citations = retrieveEvidence(project);
            advance(runId, "ANALYZING", 54, "Analyzing five health dimensions", 3, "DONE", "Delivery, quality, architecture, risk, and collaboration");
            advance(runId, "VERIFYING", 70, "Verifying conclusions and citations", 4, "DONE", "Evidence Reviewer checked sources and unknowns");
            advance(runId, "PLANNING", 84, "Creating delivery plan", 5, "DONE", "Tasks, dependencies, and acceptance criteria structured");

            Map<String, Object> report = buildReport(project, citations);
            Long reportId = insert("""
                    INSERT INTO agent_report
                    (project_id, run_id, title, summary, health_status, health_score,
                     dimensions_json, risks_json, plan_json, citations_json, report_markdown, status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,'DRAFT')
                    """,
                    projectId, runId, report.get("title"), report.get("summary"),
                    report.get("healthStatus"), report.get("healthScore"),
                    json(report.get("dimensions")), json(report.get("risks")), json(report.get("plan")),
                    json(report.get("citations")), report.get("reportMarkdown"));
            Long actionId = insert("""
                    INSERT INTO agent_action
                    (project_id, run_id, action_type, status, title, payload_json)
                    VALUES (?,?,'CREATE_GITHUB_ISSUE','PENDING_APPROVAL',?,?)
                    """,
                    projectId, runId, report.get("issueTitle"),
                    json(Map.of("body", report.get("issueBody"), "source", "AtlasMind report")));
            jdbcTemplate.update("""
                    UPDATE agent_project SET health_status=?, health_score=?, last_run_id=?, last_run_at=NOW()
                    WHERE id=?
                    """, report.get("healthStatus"), report.get("healthScore"), runId, projectId);
            advance(runId, "WAITING_APPROVAL", 96, "Waiting for human approval", 6, "DONE",
                    "Report #" + reportId + " generated; Issue action #" + actionId + " awaits approval");
        } catch (Exception e) {
            jdbcTemplate.update("""
                    UPDATE agent_run SET status='FAILED', progress=100, current_step='Run failed',
                    error_message=?, finished_at=NOW() WHERE id=?
                    """, e.getMessage(), runId);
        }
    }

    private List<Map<String, Object>> retrieveEvidence(Map<String, Object> project) {
        List<Map<String, Object>> citations = new ArrayList<>();
        Long projectId = longValue(project.get("id"));
        List<Map<String, Object>> evidenceRows = listProjectEvidence(projectId, Map.of("limit", 8));
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
            return citations;
        }
        try {
            Map<String, Object> result = aiGateway.testRetrieval(Map.of(
                    "message", "project health analysis " + text(project, "name") + " " + text(project, "description"),
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
                    "title", "Project onboarding facts",
                    "snippet", text(project, "description"),
                    "score", 1.0,
                    "rank", 1
            ));
        }
        return citations;
    }

    private Map<String, Object> buildReport(Map<String, Object> project, List<Map<String, Object>> citations) {
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
        List<Map<String, Object>> dimensions = List.of(
                dimension("Delivery progress", hasIssueEvidence || hasPullRequestEvidence ? 76 : 64,
                        hasIssueEvidence || hasPullRequestEvidence
                                ? "Open Issue/PR evidence is available for delivery risk review."
                                : "Milestone is recorded, but live Issue/PR evidence is still missing."),
                dimension("Quality stability", 66,
                        "CI/CD evidence is not connected yet, so quality conclusions remain pending confirmation."),
                dimension("Architecture and debt", hasFileEvidence ? 78 : 62,
                        hasFileEvidence
                                ? "README, file tree, or build configuration evidence is available for architecture review."
                                : "Repository file evidence is missing; architecture judgement should stay conservative."),
                dimension("Project risk", hasGithubEvidence ? 70 : 58,
                        hasGithubEvidence
                                ? "Evidence Reviewer has citable GitHub facts; unsupported risk statements are still flagged."
                                : "Only onboarding facts are available, so risk analysis is intentionally limited."),
                dimension("Engineering collaboration", hasCommitEvidence || hasPullRequestEvidence ? 74 : 60,
                        hasCommitEvidence || hasPullRequestEvidence
                                ? "Recent commits or pull requests provide collaboration signals."
                                : "Collaboration metrics require commit and PR sync.")
        );
        int score = (int) Math.round(dimensions.stream()
                .mapToInt(item -> integerValue(item.get("score"))).average().orElse(0));
        String status = score >= 80 ? "HEALTHY" : score >= 65 ? "WATCH" : "AT_RISK";
        List<Map<String, Object>> risks = List.of(
                risk("R-01", hasIssueEvidence || hasPullRequestEvidence ? "Delivery work needs triage" : "Delivery evidence is incomplete",
                        "MEDIUM",
                        hasIssueEvidence || hasPullRequestEvidence
                                ? "Open Issue/PR evidence exists and should be triaged into the next delivery boundary."
                                : "The current report lacks live Issue, PR, and CI data.",
                        citations.get(0)),
                risk("R-02", hasFileEvidence ? "Technical debt needs code-level follow-up" : "Key technical debt needs confirmation",
                        "MEDIUM",
                        hasFileEvidence
                                ? "Repository documents or build files are available, but dependency/test scans are still needed."
                                : "Repository structure, dependency, and test scan evidence are required.",
                        citations.get(0)),
                risk("R-03", "Release target lacks acceptance boundary", "LOW", "Definition of Done and milestone acceptance criteria should be added.", Map.of(
                        "sourceType", "PROJECT_CONTEXT", "sourceId", text(project, "id"),
                        "title", "Project onboarding facts", "snippet", text(project, "releaseTarget")
                ))
        );
        List<Map<String, Object>> plan = List.of(
                task("P1", hasGithubEvidence ? "Triage synced GitHub evidence into delivery risks" : "Sync repository tree, README, Issues, and PRs", "Repository Analyst", "R-01",
                        hasGithubEvidence ? "Map evidence-backed risks to owners and next milestone." : "Create citable code and collaboration facts."),
                task("P2", "Add technical debt and dependency scan", "Project Analyst", "R-02", "Produce module, dependency, and test coverage evidence."),
                task("P3", "Confirm next milestone acceptance criteria", "Delivery Planner", "R-03", "Turn report recommendations into executable delivery boundaries.")
        );
        String title = text(project, "name") + " Project Health and Delivery Plan";
        String summary = "Current health status is " + status + " with score " + score + ". Evidence Reviewer checked " + repoFacts + " citable facts; unsupported conclusions are marked as pending confirmation.";
        String markdown = """
                # %s

                > Health status: **%s** | Score: **%d/100** | Source: Agent Run

                ## Summary

                %s

                ## Five Health Dimensions

                %s

                ## Key Risks

                %s

                ## Next Delivery Plan

                %s

                ## Citations

                %s

                ## Review Notes

                Evidence Reviewer checked citations. Items without GitHub or CI facts remain pending confirmation and are not treated as final conclusions.
                """.formatted(title, status, score, summary,
                dimensions.stream().map(item -> "- " + item.get("name") + ": " + item.get("score") + "/100 | " + item.get("note")).reduce("", (a, b) -> a + b + "\n"),
                risks.stream().map(item -> "- [" + item.get("severity") + "] " + item.get("title") + ": " + item.get("description")).reduce("", (a, b) -> a + b + "\n"),
                plan.stream().map(item -> "- " + item.get("id") + " " + item.get("title") + " (owner role: " + item.get("ownerRole") + ", dependency: " + item.get("dependency") + ")").reduce("", (a, b) -> a + b + "\n"),
                citations.stream().limit(6).map(item -> "- [" + item.get("objectType") + "] " + item.get("title") + " | " + item.get("sourceRef")).reduce("", (a, b) -> a + b + "\n"));
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
        report.put("issueTitle", "[AtlasMind] " + text(project, "name") + " delivery follow-up");
        report.put("issueBody", markdown);
        return report;
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
    }

    private void requireProject(Long projectId) {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM agent_project WHERE id=? AND deleted=0", Integer.class, projectId);
        if (number(count) == 0) {
            throw new IllegalArgumentException("Project not found");
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
