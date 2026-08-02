package com.atlasmind.service;

import java.util.List;
import java.util.Map;

/**
 * Contract case lifecycle management — the new core business object
 * replacing agent_project for the ContractOps product mode.
 */
public interface ContractCaseService {

    Map<String, Object> portfolio();

    List<Map<String, Object>> listCases(Map<String, Object> filters);

    Map<String, Object> getCase(Long caseId);

    Map<String, Object> createCase(Map<String, Object> request);

    Map<String, Object> updateCase(Long caseId, Map<String, Object> request);

    Map<String, Object> uploadDocument(Long caseId, Map<String, Object> request);

    List<Map<String, Object>> listDocuments(Long caseId);

    Map<String, Object> startRun(Long caseId, Map<String, Object> request);

    List<Map<String, Object>> listRuns(Long caseId);

    Map<String, Object> getRun(Long runId);

    Map<String, Object> approveAction(Long runId, Long actionId, Map<String, Object> request, String approvedBy);

    Map<String, Object> executeAction(Long runId, Long actionId);
}
