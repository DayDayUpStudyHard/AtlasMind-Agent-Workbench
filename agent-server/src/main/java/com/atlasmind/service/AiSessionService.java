package com.atlasmind.service;

import com.atlasmind.entity.KbQaMessage;
import com.atlasmind.entity.KbQaSession;

import java.util.List;
import java.util.Map;

/**
 * 用户端 AI 会话持久化接口。
 */
public interface AiSessionService {

    KbQaSession createSession(Map<String, Object> request);

    KbQaSession requireSession(Long sessionId, String ownerToken);

    List<KbQaMessage> listMessages(Long sessionId, String ownerToken);

    KbQaMessage appendMessage(Long sessionId, String ownerToken, Map<String, Object> request);
}
