package com.atlasmind.agent.runtime;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class AgentExecutionPolicyTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void blocksAnIdenticalToolCall() {
        AgentExecutionPolicy policy = new AgentExecutionPolicy(4, 2, Duration.ofSeconds(5), objectMapper);

        policy.reserveToolCall("searchProjectEvidence", Map.of("query", "CI", "limit", 5));

        assertThrows(AgentExecutionPolicy.RepeatedToolCallException.class,
                () -> policy.reserveToolCall("searchProjectEvidence", Map.of("query", "CI", "limit", 5)));
        assertEquals(3, policy.remainingToolCalls());
    }

    @Test
    void stopsAtTheToolCallBudget() {
        AgentExecutionPolicy policy = new AgentExecutionPolicy(2, 2, Duration.ofSeconds(5), objectMapper);

        policy.reserveToolCall("getProjectProfile", Map.of());
        policy.reserveToolCall("getProjectMemory", Map.of("limit", 5));

        assertThrows(AgentExecutionPolicy.BudgetExceededException.class,
                () -> policy.reserveToolCall("getRecentRuns", Map.of("limit", 5)));
        assertEquals(0, policy.remainingToolCalls());
    }

    @Test
    void stopsAtTheTurnBudget() {
        AgentExecutionPolicy policy = new AgentExecutionPolicy(2, 1, Duration.ofSeconds(5), objectMapper);

        policy.beginTurn();

        assertThrows(AgentExecutionPolicy.BudgetExceededException.class, policy::beginTurn);
    }
}
