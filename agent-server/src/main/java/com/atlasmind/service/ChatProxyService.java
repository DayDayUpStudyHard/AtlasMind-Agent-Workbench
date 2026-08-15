package com.atlasmind.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

/** Streams authenticated browser chat requests to the internal AI service. */
@Service
@RequiredArgsConstructor
public class ChatProxyService {

    private final ObjectMapper objectMapper;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(3))
            .build();

    @Value("${atlasmind.chat-assistant.url:http://localhost:18088}")
    private String baseUrl;

    @Value("${atlasmind.chat-assistant.token:}")
    private String internalToken;

    @Value("${atlasmind.chat-assistant.stream-timeout-seconds:300}")
    private long streamTimeoutSeconds;

    public InputStream stream(Map<String, Object> payload, long userId) {
        if (internalToken == null || internalToken.isBlank()) {
            throw new IllegalStateException("AI service token is not configured");
        }
        try {
            String normalizedBaseUrl = baseUrl == null ? "" : baseUrl.replaceAll("/+$", "");
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(normalizedBaseUrl + "/api/chat/send"))
                    .timeout(Duration.ofSeconds(Math.max(1, streamTimeoutSeconds)))
                    .header("Content-Type", "application/json")
                    .header("Accept", "text/event-stream")
                    .header("X-Internal-Token", internalToken)
                    .header("X-User-Id", String.valueOf(userId))
                    .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(payload)))
                    .build();
            HttpResponse<InputStream> response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
            if (response.statusCode() >= 400) {
                try (InputStream body = response.body()) {
                    body.readAllBytes();
                }
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "AI service rejected the request");
            }
            return response.body();
        } catch (ResponseStatusException e) {
            throw e;
        } catch (IOException | InterruptedException e) {
            if (e instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "AI service is unavailable", e);
        }
    }
}
