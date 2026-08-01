package com.atlasmind.agent.runtime;

import com.atlasmind.gateway.AiGateway;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Component
@RequiredArgsConstructor
public class DefaultAgentHarness implements AgentHarness {

    private static final int MAX_TOOL_CALLS = 8;
    private static final int MAX_TURNS = 2;

    private final AiGateway aiGateway;
    private final AgentToolRegistry toolRegistry;
    private final AgentTraceStore traceStore;
    private final DeterministicHealthScoringEngine scoringEngine;
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    @Override
    public AgentHarnessResult execute(AgentTaskContext context) {
        AgentExecutionPolicy policy = new AgentExecutionPolicy(
                MAX_TOOL_CALLS, MAX_TURNS, Duration.ofSeconds(300), objectMapper);
        List<Map<String, Object>> observations = new ArrayList<>();
        String executionMode = "native-function-calling";

        updateRun(context.runId(), "CONTEXT_BUILDING", 8, "Harness 正在加载项目记忆");
        executeTool(context, policy, observations, "bootstrap-memory", "getProjectMemory", Map.of("limit", 12));
        traceStore.trace(context.runId(), "MEMORY_LOADED", "已加载项目记忆",
                Map.of("memoryObservations", observations.size()));

        Map<String, Object> plan;
        try {
            plan = aiGateway.planAgent(Map.of(
                    "task", taskPayload(context),
                    "memory", observations,
                    "availableTools", toolRegistry.definitions(),
                    "limits", Map.of("maxToolCalls", MAX_TOOL_CALLS, "maxTurns", MAX_TURNS)
            ));
        } catch (Exception e) {
            executionMode = "structured-planner-fallback";
            plan = fallbackPlan(context.taskType(), e.getMessage());
        }
        traceStore.trace(context.runId(), "PLAN_CREATED", "Planner 已生成有界执行计划", plan);
        updateRun(context.runId(), "PLANNING", 18, "Planner 已生成执行计划");

        boolean plannerFinished = false;
        for (int turnIndex = 0; turnIndex < MAX_TURNS && policy.remainingToolCalls() > 2; turnIndex++) {
            try {
                policy.beginTurn();
            } catch (AgentExecutionPolicy.BudgetExceededException e) {
                traceStore.trace(context.runId(), "BUDGET_EXHAUSTED", e.getMessage(), Map.of());
                break;
            }
            updateRun(context.runId(), "ANALYZING", Math.min(62, 25 + turnIndex * 9),
                    "Agent 正在选择并调用工具");
            Map<String, Object> turn;
            try {
                turn = aiGateway.nextAgentTurn(Map.of(
                        "task", taskPayload(context),
                        "plan", plan,
                        "observations", boundedObservations(observations),
                        "availableTools", toolRegistry.definitions(),
                        "remainingToolCalls", policy.remainingToolCalls(),
                        "turn", turnIndex + 1
                ));
                String providerMode = text(turn, "providerMode");
                if (!providerMode.isBlank()) executionMode = providerMode;
            } catch (Exception e) {
                executionMode = "structured-tool-fallback";
                turn = fallbackTurn(context.taskType(), observations, e.getMessage());
                traceStore.trace(context.runId(), "TOOL_SELECTION_FALLBACK",
                        "原生 Function Calling 不可用，启用可见降级策略",
                        Map.of("error", safeMessage(e)));
            }

            List<Map<String, Object>> calls = mapList(turn.get("toolCalls"));
            if (calls.isEmpty()) {
                plannerFinished = "final".equalsIgnoreCase(text(turn, "mode"));
                if (plannerFinished) break;
                continue;
            }
            for (Map<String, Object> call : calls) {
                if (policy.remainingToolCalls() <= 2) break;
                String toolName = text(call, "name");
                if (toolName.isBlank() || !toolRegistry.supports(toolName)) {
                    traceStore.trace(context.runId(), "TOOL_FAILED", "Planner 请求了无效工具",
                            Map.of("toolName", toolName, "reason", "not allowlisted"));
                    continue;
                }
                Map<String, Object> arguments = objectMap(call.get("arguments"));
                executeTool(context, policy, observations,
                        value(call, "planStepId", "turn-" + (turnIndex + 1)), toolName, arguments);
            }
        }

        ensureEvidenceAndScoring(context, policy, observations);
        List<Map<String, Object>> citations = toolRegistry.citationsFrom(observations);
        Map<String, Object> scoring = toolRegistry.scoringFrom(observations);

        updateRun(context.runId(), "VERIFYING", 72, "Reflection 正在核验证据覆盖与引用");
        traceStore.trace(context.runId(), "REFLECTION_STARTED", "开始检查证据覆盖、引用和任务完成度",
                Map.of("observationCount", observations.size(), "citationCount", citations.size()));
        Map<String, Object> reflection;
        try {
            reflection = aiGateway.reflectAgent(Map.of(
                    "task", taskPayload(context),
                    "plan", plan,
                    "observations", boundedObservations(observations),
                    "citationCount", citations.size(),
                    "plannerFinished", plannerFinished
            ));
        } catch (Exception e) {
            reflection = localReflection(context, observations, citations, e.getMessage());
        }

        if (!booleanValue(reflection.get("adequate"), false) && policy.remainingToolCalls() > 0) {
            traceStore.trace(context.runId(), "REPLAN_REQUESTED", "Reflection 发现证据缺口，执行补充工具",
                    reflection);
            for (Map<String, Object> call : mapList(reflection.get("suggestedToolCalls"))) {
                if (policy.remainingToolCalls() <= 0) break;
                executeTool(context, policy, observations, "reflection-replan",
                        text(call, "name"), objectMap(call.get("arguments")));
            }
            citations = toolRegistry.citationsFrom(observations);
        }
        if ("HEALTH_ANALYSIS".equals(context.taskType()) && scoring.isEmpty()) {
            executeTool(context, policy, observations, "reflection-score-refresh",
                    "calculateHealthScore", Map.of("snapshotRevision", "post-reflection"));
            scoring = toolRegistry.scoringFrom(observations);
        }
        traceStore.trace(context.runId(), booleanValue(reflection.get("adequate"), false)
                        ? "REFLECTION_PASSED" : "REFLECTION_FAILED",
                value(reflection, "summary", "Reflection 已完成"), reflection);

        updateRun(context.runId(), "PLANNING", 86, "执行器正在生成结构化产物");
        Map<String, Object> rawArtifact;
        try {
            rawArtifact = generateArtifact(context, citations, scoring);
            traceStore.trace(context.runId(), "ARTIFACT_CREATED", "结构化任务产物已生成",
                    Map.of("taskType", context.taskType(), "citationCount", citations.size(),
                            "executionMode", executionMode));
        } catch (Exception e) {
            rawArtifact = Map.of("artifactError", safeMessage(e));
            traceStore.trace(context.runId(), "ARTIFACT_FAILED",
                    "LLM 产物生成失败，将由规则执行器兜底", Map.of("error", safeMessage(e)));
        }
        persistEpisodicMemory(context, observations, reflection);

        return new AgentHarnessResult(plan, List.copyOf(observations), List.copyOf(citations),
                scoring, reflection, rawArtifact, executionMode);
    }

    private void ensureEvidenceAndScoring(AgentTaskContext context, AgentExecutionPolicy policy,
                                          List<Map<String, Object>> observations) {
        if (toolRegistry.citationsFrom(observations).isEmpty() && policy.remainingToolCalls() > 0) {
            executeTool(context, policy, observations, "harness-required-evidence", "searchProjectEvidence",
                    Map.of("query", "", "limit", 12));
        }
        if ("HEALTH_ANALYSIS".equals(context.taskType())
                && toolRegistry.scoringFrom(observations).isEmpty()
                && policy.remainingToolCalls() > 0) {
            executeTool(context, policy, observations, "harness-required-scoring", "calculateHealthScore", Map.of());
        }
    }

    private void executeTool(AgentTaskContext context, AgentExecutionPolicy policy,
                             List<Map<String, Object>> observations, String planStepId,
                             String toolName, Map<String, Object> arguments) {
        String callId = UUID.randomUUID().toString();
        traceStore.toolStarted(context.runId(), planStepId, callId, toolName, arguments);
        long startedAt = System.nanoTime();
        try {
            policy.reserveToolCall(toolName, arguments);
            Map<String, Object> output = toolRegistry.execute(context, toolName, arguments, observations);
            long latency = elapsedMillis(startedAt);
            traceStore.toolCompleted(context.runId(), callId, toolName, output, latency);
            Map<String, Object> observation = new HashMap<>();
            observation.put("callId", callId);
            observation.put("planStepId", planStepId);
            observation.put("toolName", toolName);
            observation.put("arguments", arguments);
            observation.put("output", output);
            observation.put("status", "DONE");
            observations.add(observation);
        } catch (Exception e) {
            long latency = elapsedMillis(startedAt);
            traceStore.toolFailed(context.runId(), callId, toolName, safeMessage(e), latency);
            observations.add(Map.of(
                    "callId", callId,
                    "planStepId", planStepId,
                    "toolName", toolName,
                    "arguments", arguments,
                    "status", "FAILED",
                    "error", safeMessage(e)
            ));
        }
    }

    private Map<String, Object> generateArtifact(AgentTaskContext context,
                                                  List<Map<String, Object>> citations,
                                                  Map<String, Object> scoring) {
        if ("HEALTH_ANALYSIS".equals(context.taskType())) {
            Map<String, Object> effectiveScoring = scoring.isEmpty()
                    ? scoringEngine.score(context.project(), citations) : scoring;
            return aiGateway.analyzeProject(Map.of(
                    "project", context.project(),
                    "citations", citations,
                    "deterministicScoring", effectiveScoring
            ));
        }
        return aiGateway.runProjectTask(Map.of(
                "taskType", context.taskType(),
                "project", context.project(),
                "taskInput", context.taskInput(),
                "citations", citations
        ));
    }

    private void persistEpisodicMemory(AgentTaskContext context,
                                       List<Map<String, Object>> observations,
                                       Map<String, Object> reflection) {
        String tools = observations.stream().map(item -> text(item, "toolName")).distinct()
                .reduce((left, right) -> left + ", " + right).orElse("无");
        String content = "任务：" + context.question() + "\n调用工具：" + tools
                + "\n反思：" + value(reflection, "summary", "未返回反思摘要");
        jdbcTemplate.update("""
                INSERT INTO agent_project_memory
                (project_id, memory_type, title, content, source_type, source_id, confirmed)
                VALUES (?, 'EPISODIC', ?, ?, 'AGENT_RUN', ?, 0)
                """, context.projectId(), "Agent Run #" + context.runId() + " 执行记忆",
                content, String.valueOf(context.runId()));
        traceStore.trace(context.runId(), "MEMORY_WRITTEN", "已写入待确认的情节记忆",
                Map.of("memoryType", "EPISODIC", "confirmed", false));
    }

    private Map<String, Object> fallbackPlan(String taskType, String reason) {
        return Map.of(
                "goal", "完成 " + taskType + " 并形成可审计产物",
                "plannerMode", "fallback",
                "fallbackReason", reason == null ? "planner unavailable" : reason,
                "steps", List.of(
                        Map.of("id", "P1", "title", "读取项目上下文和记忆", "suggestedTools", List.of("getProjectProfile", "getProjectMemory")),
                        Map.of("id", "P2", "title", "检索项目证据和适用知识", "suggestedTools", List.of("searchProjectEvidence", "searchProjectKnowledge")),
                        Map.of("id", "P3", "title", "核验覆盖并生成产物", "suggestedTools", List.of("getRecentRuns"))
                )
        );
    }

    private Map<String, Object> fallbackTurn(String taskType,
                                              List<Map<String, Object>> observations,
                                              String reason) {
        boolean hasEvidence = observations.stream()
                .anyMatch(item -> "searchProjectEvidence".equals(text(item, "toolName")));
        boolean hasKnowledge = observations.stream()
                .anyMatch(item -> "searchProjectKnowledge".equals(text(item, "toolName")));
        List<Map<String, Object>> calls = new ArrayList<>();
        if (!hasEvidence) {
            calls.add(Map.of("name", "searchProjectEvidence", "planStepId", "P2",
                    "arguments", Map.of("query", "", "limit", 12)));
        }
        if (!hasKnowledge) {
            calls.add(Map.of("name", "searchProjectKnowledge", "planStepId", "P2",
                    "arguments", Map.of("query", taskType, "limit", 5)));
        }
        if (calls.isEmpty()) {
            calls.add(Map.of("name", "getRecentRuns", "planStepId", "P3",
                    "arguments", Map.of("limit", 5)));
        }
        return Map.of("mode", "tool_calls", "toolCalls", calls,
                "providerMode", "structured-tool-fallback", "fallbackReason", safe(reason));
    }

    private Map<String, Object> localReflection(AgentTaskContext context,
                                                List<Map<String, Object>> observations,
                                                List<Map<String, Object>> citations,
                                                String reason) {
        boolean adequate = !citations.isEmpty();
        List<Map<String, Object>> suggested = adequate ? List.of() : List.of(
                Map.of("name", "searchProjectEvidence", "arguments", Map.of("query", "", "limit", 12)));
        return Map.of(
                "adequate", adequate,
                "summary", adequate ? "本地反思确认已有可引用项目证据" : "本地反思发现项目证据为空",
                "missingEvidence", adequate ? List.of() : List.of("项目仓库或绑定知识证据"),
                "suggestedToolCalls", suggested,
                "reflectionMode", "local-fallback",
                "fallbackReason", safe(reason),
                "taskType", context.taskType(),
                "observationCount", observations.size()
        );
    }

    private Map<String, Object> taskPayload(AgentTaskContext context) {
        Map<String, Object> task = new HashMap<>();
        task.put("runId", context.runId());
        task.put("projectId", context.projectId());
        task.put("taskType", context.taskType());
        task.put("question", context.question());
        task.put("project", context.project());
        task.put("taskInput", context.taskInput());
        return task;
    }

    private List<Map<String, Object>> boundedObservations(List<Map<String, Object>> observations) {
        return observations.stream().skip(Math.max(0, observations.size() - 12L)).toList();
    }

    private void updateRun(Long runId, String status, int progress, String currentStep) {
        jdbcTemplate.update("""
                UPDATE agent_run SET status=?, progress=?, current_step=?, error_message=NULL
                WHERE id=?
                """, status, progress, currentStep, runId);
    }

    private List<Map<String, Object>> mapList(Object value) {
        if (!(value instanceof List<?> list)) return List.of();
        List<Map<String, Object>> result = new ArrayList<>();
        for (Object item : list) result.add(objectMap(item));
        return result;
    }

    private Map<String, Object> objectMap(Object value) {
        if (!(value instanceof Map<?, ?> map)) return Map.of();
        Map<String, Object> result = new HashMap<>();
        map.forEach((key, item) -> result.put(String.valueOf(key), item));
        return result;
    }

    private boolean booleanValue(Object value, boolean fallback) {
        if (value instanceof Boolean bool) return bool;
        return value == null ? fallback : Boolean.parseBoolean(String.valueOf(value));
    }

    private String value(Map<String, Object> source, String key, String fallback) {
        String value = text(source, key);
        return value.isBlank() ? fallback : value;
    }

    private String text(Map<String, Object> source, String key) {
        Object value = source == null ? null : source.get(key);
        return value == null ? "" : String.valueOf(value);
    }

    private String safeMessage(Exception exception) {
        return exception.getMessage() == null ? exception.getClass().getSimpleName() : exception.getMessage();
    }

    private String safe(String value) {
        return value == null ? "" : value;
    }

    private long elapsedMillis(long startedAt) {
        return Math.max(0, (System.nanoTime() - startedAt) / 1_000_000);
    }
}
