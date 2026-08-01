package com.atlasmind.agent.runtime;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Enforces bounded, non-repeating execution independently from the planner. */
public final class AgentExecutionPolicy {

    private final int maxToolCalls;
    private final int maxTurns;
    private final Instant deadline;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final Set<String> signatures = new HashSet<>();
    private int toolCalls;
    private int turns;

    public AgentExecutionPolicy(int maxToolCalls, int maxTurns, Duration timeout,
                                ObjectMapper objectMapper) {
        this(maxToolCalls, maxTurns, timeout, objectMapper, Clock.systemUTC());
    }

    AgentExecutionPolicy(int maxToolCalls, int maxTurns, Duration timeout,
                         ObjectMapper objectMapper, Clock clock) {
        if (maxToolCalls < 1 || maxTurns < 1 || timeout.isZero() || timeout.isNegative()) {
            throw new IllegalArgumentException("Agent execution limits must be positive");
        }
        this.maxToolCalls = maxToolCalls;
        this.maxTurns = maxTurns;
        this.deadline = clock.instant().plus(timeout);
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    public void beginTurn() {
        if (clock.instant().isAfter(deadline)) {
            throw new BudgetExceededException("Agent execution time budget exceeded");
        }
        if (++turns > maxTurns) {
            throw new BudgetExceededException("Agent turn budget exceeded");
        }
    }

    public void reserveToolCall(String toolName, Map<String, Object> arguments) {
        if (clock.instant().isAfter(deadline)) {
            throw new BudgetExceededException("Agent execution time budget exceeded");
        }
        if (toolCalls >= maxToolCalls) {
            throw new BudgetExceededException("Agent tool-call budget exceeded");
        }
        String signature = toolName + ":" + canonicalJson(arguments);
        if (!signatures.add(signature)) {
            throw new RepeatedToolCallException("Repeated tool call blocked: " + toolName);
        }
        toolCalls++;
    }

    public int remainingToolCalls() {
        return Math.max(0, maxToolCalls - toolCalls);
    }

    private String canonicalJson(Map<String, Object> arguments) {
        try {
            return objectMapper.writeValueAsString(arguments == null ? Map.of() : arguments);
        } catch (JsonProcessingException e) {
            return String.valueOf(arguments);
        }
    }

    public static final class BudgetExceededException extends IllegalStateException {
        public BudgetExceededException(String message) {
            super(message);
        }
    }

    public static final class RepeatedToolCallException extends IllegalStateException {
        public RepeatedToolCallException(String message) {
            super(message);
        }
    }
}
