package com.atlasmind.agent.runtime;

import java.util.Map;

public record AgentTaskContext(
        Long runId,
        Long projectId,
        String taskType,
        String question,
        Map<String, Object> project,
        Map<String, Object> taskInput
) {
}
