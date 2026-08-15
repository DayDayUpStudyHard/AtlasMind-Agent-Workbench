package com.atlasmind.controller;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.entity.KbQaSession;
import com.atlasmind.service.AiSessionService;
import com.atlasmind.service.ChatProxyService;
import com.atlasmind.service.ContractAccessPolicy;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.InputStream;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Map;
import java.util.List;

/** Browser-facing chat endpoint. Authentication and scope checks happen before AI forwarding. */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/chat")
public class ChatController {

    private final AiSessionService aiSessionService;
    private final ChatProxyService chatProxyService;
    private final ContractAccessPolicy contractAccessPolicy;
    private final StringRedisTemplate redisTemplate;

    @Value("${atlasmind.chat-assistant.rate-limit-per-minute:12}")
    private int rateLimitPerMinute;

    @PostMapping(value = "/send", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<StreamingResponseBody> send(@RequestBody Map<String, Object> payload) {
        long userId = StpUtil.getLoginIdAsLong();
        enforceRateLimit(userId);
        Long caseId = authorizeChatScope(payload);
        if (caseId != null) {
            payload.put("caseId", caseId);
            payload.put("projectId", caseId);
        }

        InputStream upstream = chatProxyService.stream(payload, userId);
        StreamingResponseBody response = outputStream -> {
            try (upstream) {
                upstream.transferTo(outputStream);
                outputStream.flush();
            }
        };
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .cacheControl(CacheControl.noStore())
                .header("X-Accel-Buffering", "no")
                .header(HttpHeaders.CONNECTION, "keep-alive")
                .body(response);
    }

    @GetMapping("/suggestions")
    public Map<String, List<String>> suggestions() {
        return Map.of("suggestions", List.of(
                "帮我梳理当前合同的关键风险。",
                "这份合同的付款条件是什么？",
                "有哪些履约节点需要关注？"
        ));
    }

    private Long authorizeChatScope(Map<String, Object> payload) {
        Long requestedCaseId = longValue(payload.get("caseId"));
        if (requestedCaseId == null) {
            requestedCaseId = longValue(payload.get("projectId"));
        }
        Long sessionId = longValue(payload.get("sessionId"));
        if (sessionId != null) {
            KbQaSession session = aiSessionService.requireSession(sessionId, stringValue(payload.get("ownerToken")));
            Long sessionCaseId = session.getCaseId();
            if (sessionCaseId != null && requestedCaseId != null && !sessionCaseId.equals(requestedCaseId)) {
                throw new IllegalArgumentException("AI session scope cannot be changed");
            }
            if (sessionCaseId != null) {
                requestedCaseId = sessionCaseId;
            }
        }
        if (requestedCaseId != null) {
            contractAccessPolicy.checkAccess(requestedCaseId);
        }
        return requestedCaseId;
    }

    private void enforceRateLimit(long userId) {
        int limit = Math.max(1, rateLimitPerMinute);
        Instant now = Instant.now();
        String key = "chat:rate:" + userId + ":" + now.truncatedTo(ChronoUnit.MINUTES).getEpochSecond();
        Long count = redisTemplate.opsForValue().increment(key);
        if (count != null && count == 1) {
            redisTemplate.expire(key, Duration.ofMinutes(2));
        }
        if (count != null && count > limit) {
            throw new IllegalStateException("Chat request limit reached; please try again shortly");
        }
    }

    private Long longValue(Object value) {
        if (value instanceof Number number) return number.longValue();
        if (value == null) return null;
        try {
            return Long.valueOf(String.valueOf(value));
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private String stringValue(Object value) {
        return value == null ? null : String.valueOf(value);
    }
}
