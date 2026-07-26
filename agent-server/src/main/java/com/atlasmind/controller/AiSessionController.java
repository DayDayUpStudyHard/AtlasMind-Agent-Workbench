package com.atlasmind.controller;

import com.atlasmind.common.Result;
import com.atlasmind.entity.KbQaMessage;
import com.atlasmind.entity.KbQaSession;
import com.atlasmind.service.AiSessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 用户端 AI 会话接口。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/ai/sessions")
public class AiSessionController {

    private final AiSessionService aiSessionService;

    @PostMapping
    public Result<KbQaSession> create(@RequestBody(required = false) Map<String, Object> request) {
        return Result.ok(aiSessionService.createSession(request == null ? Map.of() : request));
    }

    @GetMapping("/{id}/messages")
    public Result<List<KbQaMessage>> messages(
            @PathVariable Long id,
            @RequestHeader(value = "X-AI-Session-Token", required = false) String ownerToken) {
        return Result.ok(aiSessionService.listMessages(id, ownerToken));
    }

    @PostMapping("/{id}/messages")
    public Result<KbQaMessage> append(
            @PathVariable Long id,
            @RequestHeader(value = "X-AI-Session-Token", required = false) String ownerToken,
            @RequestBody Map<String, Object> request) {
        return Result.ok(aiSessionService.appendMessage(id, ownerToken, request));
    }
}
