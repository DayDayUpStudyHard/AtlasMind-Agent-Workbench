package com.atlasmind.agent.runtime;

import java.util.List;
import java.util.Map;

public record AgentHarnessResult(
        Map<String, Object> plan,
        List<Map<String, Object>> observations,
        List<Map<String, Object>> citations,
        Map<String, Object> deterministicScoring,
        Map<String, Object> reflection,
        Map<String, Object> rawArtifact,
        String executionMode
) {
}
