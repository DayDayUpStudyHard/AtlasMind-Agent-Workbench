package com.atlasmind.gateway;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.entity.User;
import com.atlasmind.service.UserService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

/**
 * 基于 Java HttpClient 的 AI 微服务适配器。
 */
@Component
@RequiredArgsConstructor
public class HttpAiGateway implements AiGateway {

    private final ObjectMapper objectMapper;
    private final UserService userService;
    private final Environment environment;

    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(3))
            .build();

    @Value("${atlasmind.chat-assistant.url:http://localhost:18088}")
    private String baseUrl;

    @Value("${atlasmind.chat-assistant.timeout-seconds:12}")
    private long timeoutSeconds;

    @Value("${atlasmind.chat-assistant.project-analysis-timeout-seconds:120}")
    private long projectAnalysisTimeoutSeconds;

    @Value("${atlasmind.chat-assistant.evaluation-recompute-timeout-seconds:180}")
    private long evaluationRecomputeTimeoutSeconds;

    @Override
    public void triggerIngest(Map<String, Object> payload) {
        post("/internal/kb/ingest/jobs", payload);
    }

    @Override
    public void triggerReindex(Long documentId, Map<String, Object> payload) {
        post("/internal/kb/documents/" + documentId + "/reindex", payload);
    }

    @Override
    public void deleteDocumentIndex(Long documentId) {
        request("DELETE", "/internal/kb/documents/" + documentId + "/index", null);
    }

    @Override
    public void parseContractDocument(Long documentId) {
        post("/internal/contract/documents/" + documentId + "/parse", Map.of());
    }

    @Override
    public void runEvaluation(Long evalRunId) {
        post("/internal/agent/evaluations/run", Map.of("evalRunId", evalRunId));
    }

    @Override
    public Map<String, Object> recomputeEvaluationGates(Map<String, Object> payload) {
        return request("POST", "/internal/agent/evaluations/recompute-gates", payload,
                evaluationRecomputeTimeoutSeconds);
    }

    @Override
    public void extractContractIntake(Long intakeId) {
        post("/internal/contract/intakes/" + intakeId + "/extract", Map.of());
    }

    @Override
    public Map<String, Object> testRetrieval(Map<String, Object> payload) {
        return post("/api/kb/qa/test", payload);
    }

    @Override
    public Map<String, Object> analyzeProject(Map<String, Object> payload) {
        return request("POST", "/internal/project-analysis", payload, projectAnalysisTimeoutSeconds);
    }

    @Override
    public Map<String, Object> runProjectTask(Map<String, Object> payload) {
        return request("POST", "/internal/project-tasks", payload, projectAnalysisTimeoutSeconds);
    }

    @Override
    public Map<String, Object> planAgent(Map<String, Object> payload) {
        return request("POST", "/internal/agent/plan", payload, projectAnalysisTimeoutSeconds);
    }

    @Override
    public Map<String, Object> nextAgentTurn(Map<String, Object> payload) {
        return request("POST", "/internal/agent/next-turn", payload, projectAnalysisTimeoutSeconds);
    }

    @Override
    public Map<String, Object> reflectAgent(Map<String, Object> payload) {
        return request("POST", "/internal/agent/reflect", payload, projectAnalysisTimeoutSeconds);
    }

    @Override
    public Map<String, Object> startAgentRun(Map<String, Object> payload) {
        return request("POST", "/internal/agent/run", payload, timeoutSeconds);
    }

    @Override
    public Map<String, Object> getAgentRun(Long runId) {
        return request("GET", "/internal/agent/run/" + runId, null, timeoutSeconds);
    }

    @Override
    public Map<String, Object> resumeAgentRun(Long runId, Map<String, Object> payload) {
        return request("POST", "/internal/agent/run/" + runId + "/resume", payload, timeoutSeconds);
    }

    @Override
    public Map<String, Object> cancelAgentRun(Long runId, Map<String, Object> payload) {
        return request("POST", "/internal/agent/run/" + runId + "/cancel", payload, timeoutSeconds);
    }

    @Override
    public Map<String, Object> health() {
        return request("GET", "/api/chat/health?probe=true", null, timeoutSeconds);
    }

    private Map<String, Object> post(String path, Map<String, Object> payload) {
        return request("POST", path, payload, timeoutSeconds);
    }

    private Map<String, Object> request(String method, String path, Map<String, Object> payload) {
        return request(method, path, payload, timeoutSeconds);
    }

    private Map<String, Object> request(String method, String path, Map<String, Object> payload, long requestTimeoutSeconds) {
        try {
            String normalizedBaseUrl = baseUrl == null
                    ? ""
                    : baseUrl.replaceAll("/+$", "");
            HttpRequest.Builder builder = HttpRequest.newBuilder()
                    .uri(URI.create(normalizedBaseUrl + path))
                    .timeout(Duration.ofSeconds(Math.max(1, requestTimeoutSeconds)));

            String internalToken = resolveInternalToken();
            if (internalToken != null && !internalToken.isBlank()) {
                builder.header("X-Internal-Token", internalToken);
            }

            // Inject current user identity (from StpUtil, never trust frontend)
            try {
                long userId = StpUtil.getLoginIdAsLong();
                builder.header("X-User-Id", String.valueOf(userId));
                User user = userService.getById(userId);
                if (user != null && user.getDepartmentId() != null) {
                    builder.header("X-Department-Id", String.valueOf(user.getDepartmentId()));
                }
            } catch (Exception ignored) {
                // Not logged in — some internal calls may not have a user context
            }

            if ("DELETE".equalsIgnoreCase(method)) {
                builder.DELETE();
            } else if ("GET".equalsIgnoreCase(method)) {
                builder.GET();
            } else {
                String json = payload == null ? "{}" : objectMapper.writeValueAsString(payload);
                builder.header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(json));
            }

            HttpResponse<String> response = httpClient.send(
                    builder.build(),
                    HttpResponse.BodyHandlers.ofString()
            );
            if (response.statusCode() >= 400) {
                throw new IllegalStateException(
                        "Python 服务返回 " + response.statusCode() + ": " + response.body()
                );
            }
            if (response.body() == null || response.body().isBlank()) {
                return Map.of();
            }
            return objectMapper.readValue(
                    response.body(),
                    new TypeReference<Map<String, Object>>() {}
            );
        } catch (Exception e) {
            throw new IllegalStateException("调用 Python AI 服务失败: " + e.getMessage(), e);
        }
    }

    private String resolveInternalToken() {
        String token = environment.getProperty("atlasmind.chat-assistant.token");
        if (token != null && !token.isBlank()) {
            return token;
        }
        token = environment.getProperty("atlasmind.internal-token");
        if (token != null && !token.isBlank()) {
            return token;
        }
        token = environment.getProperty("CHAT_ASSISTANT_TOKEN");
        if (token != null && !token.isBlank()) {
            return token;
        }
        return "";
    }
}
