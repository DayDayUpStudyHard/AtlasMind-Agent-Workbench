package com.atlasmind.service;

import java.util.List;
import java.util.Map;

/**
 * 研发项目工作台服务：项目上下文、异步 Agent Run、报告和审批动作。
 */
public interface AgentProjectService {

    Map<String, Object> overview();

    Map<String, Object> organizationOverview();

    List<Map<String, Object>> listProjects();

    Map<String, Object> getProject(Long projectId);

    Map<String, Object> createProject(Map<String, Object> request);

    Map<String, Object> syncProjectEvidence(Long projectId);

    List<Map<String, Object>> listProjectEvidence(Long projectId, Map<String, Object> request);

    List<Map<String, Object>> listSyncJobs(Long projectId);

    Map<String, Object> startRun(Long projectId, Map<String, Object> request);

    List<Map<String, Object>> listRuns(Long projectId);

    Map<String, Object> getRun(Long runId);

    Map<String, Object> approveAction(Long runId, Long actionId, Map<String, Object> request, String approvedBy);

    Map<String, Object> executeAction(Long runId, Long actionId);

    List<Map<String, Object>> listAllRuns();

    List<Map<String, Object>> listReports();

    List<Map<String, Object>> listActions(String status);

    void deleteRun(Long runId);

    void deleteReport(Long reportId);

    Map<String, Object> getMemory(Long memoryId);

    void deleteAction(Long actionId);
}
