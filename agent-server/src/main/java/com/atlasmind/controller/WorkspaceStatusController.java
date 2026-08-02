package com.atlasmind.controller;

import com.atlasmind.common.Result;
import com.atlasmind.entity.KbNotification;
import com.atlasmind.gateway.AiGateway;
import com.atlasmind.service.KnowledgeBaseService;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Workspace status: notifications, AI health, recent runs. */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/workspace")
public class WorkspaceStatusController {

    private final KnowledgeBaseService knowledgeBaseService;
    private final JdbcTemplate jdbcTemplate;
    private final AiGateway aiGateway;

    @GetMapping("/notifications")
    public Result<List<KbNotification>> notifications(
            @RequestParam(defaultValue = "false") boolean unreadOnly) {
        return Result.ok(knowledgeBaseService.listNotifications(unreadOnly));
    }

    @GetMapping("/notifications/unread-count")
    public Result<Map<String, Long>> unreadCount() {
        return Result.ok(Map.of("count", knowledgeBaseService.countUnreadNotifications()));
    }

    @PutMapping("/notifications/{id}/read")
    public Result<?> read(@PathVariable Long id) {
        knowledgeBaseService.markNotificationRead(id);
        return Result.ok();
    }

    @PutMapping("/notifications/read-all")
    public Result<?> readAll() {
        knowledgeBaseService.markAllNotificationsRead();
        return Result.ok();
    }

    @GetMapping("/ai-status")
    public Result<Map<String, Object>> aiStatus() {
        try {
            Map<String, Object> status = new HashMap<>(aiGateway.health());
            status.put("checkedAt", System.currentTimeMillis());
            return Result.ok(status);
        } catch (Exception exception) {
            return Result.ok(Map.of(
                    "status", "error",
                    "checkedAt", System.currentTimeMillis(),
                    "components", Map.of(
                            "llm", Map.of("status", "error", "message", safeMessage(exception)),
                            "embedding", Map.of("status", "unknown", "message", "AI 服务不可达"),
                            "elasticsearch", Map.of("status", "unknown", "message", "AI 服务不可达")
                    )
            ));
        }
    }

    @GetMapping("/runs/recent")
    public Result<List<Map<String, Object>>> recentRuns() {
        return Result.ok(jdbcTemplate.queryForList(
                "SELECT id, subject_type AS subjectType, run_type AS runType, status, progress, create_time AS createTime FROM agent_run ORDER BY id DESC LIMIT 20"));
    }

    private String safeMessage(Exception exception) {
        String message = exception.getMessage();
        return message == null || message.isBlank() ? exception.getClass().getSimpleName() : message;
    }
}
