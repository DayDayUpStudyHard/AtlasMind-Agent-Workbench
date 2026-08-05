package com.atlasmind.service;

import java.util.List;
import java.util.Map;

/**
 * Contract case lifecycle management — the new core business object
 * replacing agent_project for the ContractOps product mode.
 */
public interface ContractCaseService {

    Map<String, Object> portfolio();

    Map<String, Object> workQueueSummary();

    List<Map<String, Object>> listWorkQueue(String type);

    List<Map<String, Object>> listCases(Map<String, Object> filters);

    Map<String, Object> getCase(Long caseId);

    Map<String, Object> createCase(Map<String, Object> request);

    Map<String, Object> createIntake(Map<String, Object> request, Long userId);

    Map<String, Object> createFileIntake(Map<String, Object> request, Long userId);

    Map<String, Object> getIntake(Long intakeId, Long userId);

    Map<String, Object> retryIntake(Long intakeId, Long userId);

    Map<String, Object> confirmIntake(Long intakeId, Map<String, Object> request, Long userId);

    Map<String, Object> updateCase(Long caseId, Map<String, Object> request);

    Map<String, Object> uploadDocument(Long caseId, Map<String, Object> request);

    Map<String, Object> getDocumentContent(Long caseId, Long documentId);

    List<Map<String, Object>> listDocuments(Long caseId);

    List<Map<String, Object>> listRecentDocumentPipelines();

    Map<String, Object> startRun(Long caseId, Map<String, Object> request);

    List<Map<String, Object>> listRuns(Long caseId);

    Map<String, Object> getRun(Long runId);

    Map<String, Object> updateFinding(Long findingId, Map<String, Object> request);

    Map<String, Object> approveAction(Long runId, Long actionId, Map<String, Object> request, String approvedBy);

    Map<String, Object> executeAction(Long runId, Long actionId);

    Map<String, Object> startTimelineFulfillmentCheck(Long caseId, Long timelineNodeId);

    Map<String, Object> confirmFulfillmentCheck(Long checkId, Map<String, Object> request, String actor);

    Map<String, Object> getTimelineEvidenceLinks(Long caseId, Long timelineNodeId);

    Map<String, Object> saveTimelineEvidenceLinks(Long caseId, Long timelineNodeId, Map<String, Object> request);

    // Obligation management
    List<Map<String, Object>> listObligations(Long caseId);
    Map<String, Object> createObligation(Long caseId, Map<String, Object> request);
    Map<String, Object> updateObligation(Long obligationId, Map<String, Object> request);
    Map<String, Object> uploadFulfillmentEvidence(Long caseId, Map<String, Object> request);
    List<Map<String, Object>> listReminders();
}
