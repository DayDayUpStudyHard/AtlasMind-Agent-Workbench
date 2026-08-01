package com.atlasmind.agent.runtime;

import java.util.Map;

public interface AgentArtifactExecutor {

    ArtifactExecutionResult persistDraft(Long projectId, Long runId, String taskType,
                                         Map<String, Object> artifact);

    record ArtifactExecutionResult(Long reportId, Long actionId) {
    }
}
