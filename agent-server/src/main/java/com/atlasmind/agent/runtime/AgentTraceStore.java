package com.atlasmind.agent.runtime;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.Map;

@Component
@RequiredArgsConstructor
public class AgentTraceStore {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public void trace(Long runId, String eventType, String summary, Object payload) {
        Integer sequence = jdbcTemplate.queryForObject(
                "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM agent_run_trace WHERE run_id=?",
                Integer.class,
                runId
        );
        jdbcTemplate.update("""
                INSERT INTO agent_run_trace (run_id, event_type, sequence_no, summary, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """, runId, eventType, sequence == null ? 1 : sequence, abbreviate(summary, 500), json(payload));
    }

    public void toolStarted(Long runId, String planStepId, String callId,
                            String toolName, Map<String, Object> input) {
        jdbcTemplate.update("""
                INSERT INTO agent_tool_call
                (run_id, plan_step_id, call_id, tool_name, input_json, status)
                VALUES (?, ?, ?, ?, ?, 'RUNNING')
                """, runId, planStepId, callId, toolName, json(input));
        trace(runId, "TOOL_REQUESTED", "请求工具 " + toolName,
                Map.of("callId", callId, "toolName", toolName, "arguments", input));
    }

    public void toolCompleted(Long runId, String callId, String toolName,
                              Object output, long latencyMs) {
        jdbcTemplate.update("""
                UPDATE agent_tool_call
                SET status='DONE', output_json=?, latency_ms=?, error_message=NULL
                WHERE run_id=? AND call_id=?
                """, json(output), latencyMs, runId, callId);
        trace(runId, "TOOL_COMPLETED", toolName + " 返回观察结果",
                Map.of("callId", callId, "toolName", toolName, "latencyMs", latencyMs));
    }

    public void toolFailed(Long runId, String callId, String toolName,
                           String errorMessage, long latencyMs) {
        jdbcTemplate.update("""
                UPDATE agent_tool_call
                SET status='FAILED', latency_ms=?, error_message=?
                WHERE run_id=? AND call_id=?
                """, latencyMs, abbreviate(errorMessage, 4000), runId, callId);
        trace(runId, "TOOL_FAILED", toolName + " 调用失败",
                Map.of("callId", callId, "toolName", toolName,
                        "latencyMs", latencyMs, "error", abbreviate(errorMessage, 1000)));
    }

    private String json(Object value) {
        try {
            return objectMapper.writeValueAsString(value == null ? Map.of() : value);
        } catch (JsonProcessingException e) {
            return "{}";
        }
    }

    private String abbreviate(String value, int maxLength) {
        String normalized = value == null ? "" : value;
        return normalized.length() <= maxLength ? normalized : normalized.substring(0, maxLength);
    }
}
