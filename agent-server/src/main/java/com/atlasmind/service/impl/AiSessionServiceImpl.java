package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.KbQaMessage;
import com.atlasmind.entity.KbQaSession;
import com.atlasmind.mapper.KbQaMessageMapper;
import com.atlasmind.mapper.KbQaSessionMapper;
import com.atlasmind.service.AiSessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * AI 会话持久化实现。
 */
@Service
@RequiredArgsConstructor
public class AiSessionServiceImpl implements AiSessionService {

    private final KbQaSessionMapper sessionMapper;
    private final KbQaMessageMapper messageMapper;

    @Override
    public KbQaSession createSession(Map<String, Object> request) {
        KbQaSession session = new KbQaSession();
        session.setSource(stringValue(request, "source", "FRONT"));
        session.setScope(stringValue(request, "scope", "GLOBAL"));
        session.setOwnerToken(UUID.randomUUID().toString().replace("-", ""));
        session.setSpaceId(longValue(request.get("spaceId")));
        session.setDocumentId(longValue(request.get("documentId")));
        sessionMapper.insert(session);
        return session;
    }

    @Override
    public List<KbQaMessage> listMessages(Long sessionId, String ownerToken) {
        requireSession(sessionId, ownerToken);
        return messageMapper.selectList(new LambdaQueryWrapper<KbQaMessage>()
                .eq(KbQaMessage::getSessionId, sessionId)
                .orderByAsc(KbQaMessage::getCreateTime)
                .orderByAsc(KbQaMessage::getId));
    }

    @Override
    public KbQaMessage appendMessage(Long sessionId, String ownerToken, Map<String, Object> request) {
        requireSession(sessionId, ownerToken);
        String role = stringValue(request, "role", "");
        if (!List.of("user", "assistant", "system").contains(role)) {
            throw new IllegalArgumentException("消息角色不合法");
        }
        String content = stringValue(request, "content", "");
        if (content.isBlank()) {
            throw new IllegalArgumentException("消息内容不能为空");
        }

        KbQaMessage message = new KbQaMessage();
        message.setSessionId(sessionId);
        message.setRole(role);
        message.setContent(content);
        message.setModel(stringValue(request, "model", null));
        message.setLatencyMs(longValue(request.get("latencyMs")));
        messageMapper.insert(message);
        return message;
    }

    private void requireSession(Long sessionId, String ownerToken) {
        if (sessionId == null || ownerToken == null || ownerToken.isBlank()) {
            throw new IllegalArgumentException("AI 会话不存在");
        }
        KbQaSession session = sessionMapper.selectById(sessionId);
        if (session == null || session.getOwnerToken() == null
                || !MessageDigest.isEqual(
                session.getOwnerToken().getBytes(StandardCharsets.UTF_8),
                ownerToken.getBytes(StandardCharsets.UTF_8))) {
            throw new IllegalArgumentException("AI 会话不存在");
        }
    }

    private String stringValue(Map<String, Object> request, String key, String fallback) {
        Object value = request.get(key);
        return value == null ? fallback : String.valueOf(value);
    }

    private Long longValue(Object value) {
        if (value == null) return null;
        if (value instanceof Number number) return number.longValue();
        try {
            return Long.valueOf(String.valueOf(value));
        } catch (NumberFormatException ignored) {
            return null;
        }
    }
}
