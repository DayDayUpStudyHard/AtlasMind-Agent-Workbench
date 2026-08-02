package com.atlasmind.controller;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.common.Result;
import com.atlasmind.entity.User;
import com.atlasmind.service.AgentProjectService;
import com.atlasmind.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 项目总览、Agent Run、报告和审批入口。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/workspace/projects")
public class AgentWorkbenchController {

    private final AgentProjectService agentProjectService;
    private final UserService userService;
    private final StringRedisTemplate redisTemplate;

    private final ExecutorService sseExecutor = Executors.newCachedThreadPool(
            r -> new Thread(r, "sse-run-progress"));

    @GetMapping("/overview")
    public Result<Map<String, Object>> overview() {
        return Result.ok(agentProjectService.overview());
    }

    @GetMapping
    public Result<List<Map<String, Object>>> list() {
        return Result.ok(agentProjectService.listProjects());
    }

    @PostMapping
    public Result<Map<String, Object>> create(@RequestBody Map<String, Object> request) {
        return Result.ok(agentProjectService.createProject(request));
    }

    @PostMapping("/{projectId}/sync")
    public Result<Map<String, Object>> sync(@PathVariable Long projectId) {
        return Result.ok(agentProjectService.syncProjectEvidence(projectId));
    }

    @GetMapping("/{projectId}/evidence")
    public Result<List<Map<String, Object>>> evidence(
            @PathVariable Long projectId,
            @RequestParam(required = false) Map<String, Object> request) {
        return Result.ok(agentProjectService.listProjectEvidence(projectId, request == null ? Map.of() : request));
    }

    @GetMapping("/{projectId}/sync-jobs")
    public Result<List<Map<String, Object>>> syncJobs(@PathVariable Long projectId) {
        return Result.ok(agentProjectService.listSyncJobs(projectId));
    }

    @GetMapping("/{projectId}")
    public Result<Map<String, Object>> project(@PathVariable Long projectId) {
        return Result.ok(agentProjectService.getProject(projectId));
    }

    @PostMapping("/{projectId}/runs")
    public Result<Map<String, Object>> startRun(
            @PathVariable Long projectId,
            @RequestBody(required = false) Map<String, Object> request) {
        return Result.ok(agentProjectService.startRun(projectId, request == null ? Map.of() : request));
    }

    @GetMapping("/{projectId}/runs")
    public Result<List<Map<String, Object>>> runs(@PathVariable Long projectId) {
        return Result.ok(agentProjectService.listRuns(projectId));
    }

    @GetMapping("/runs/{runId}")
    public Result<Map<String, Object>> run(@PathVariable Long runId) {
        return Result.ok(agentProjectService.getRun(runId));
    }

    @PostMapping("/runs/{runId}/actions/{actionId}/approval")
    public Result<Map<String, Object>> approve(
            @PathVariable Long runId,
            @PathVariable Long actionId,
            @RequestBody(required = false) Map<String, Object> request) {
        return Result.ok(agentProjectService.approveAction(runId, actionId, request == null ? Map.of() : request, currentActor()));
    }

    /**
     * SSE endpoint that streams live Agent run progress to the frontend.
     * Subscribes to Redis PubSub channel {@code run:{runId}:progress} and
     * forwards every event as an SSE {@code progress} event.
     */
    @GetMapping(value = "/runs/{runId}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamRun(@PathVariable Long runId) {
        SseEmitter emitter = new SseEmitter(300_000L); // 5-minute timeout
        String channel = "run:" + runId + ":progress";

        sseExecutor.execute(() -> {
            final RedisConnection[] holder = new RedisConnection[1];
            try {
                holder[0] = redisTemplate.getConnectionFactory().getConnection();
                RedisConnection conn = holder[0];

                conn.subscribe((message, pattern) -> {
                    try {
                        String body = new String(message.getBody(), StandardCharsets.UTF_8);
                        emitter.send(SseEmitter.event()
                                .name("progress")
                                .data(body));
                    } catch (IOException e) {
                        // Client disconnected — close from inside the listener
                        try { holder[0].close(); } catch (Exception ignored) {}
                    }
                }, channel.getBytes(StandardCharsets.UTF_8));

                emitter.onCompletion(() -> {
                    try { holder[0].close(); } catch (Exception ignored) {}
                });
                emitter.onTimeout(() -> {
                    try { holder[0].close(); } catch (Exception ignored) {}
                });
            } catch (Exception e) {
                emitter.completeWithError(e);
                if (holder[0] != null) {
                    try { holder[0].close(); } catch (Exception ignored) {}
                }
            }
        });

        return emitter;
    }

    private String currentActor() {
        long userId = StpUtil.getLoginIdAsLong();
        User user = userService.getById(userId);
        if (user == null) {
            return "user:" + userId;
        }
        return user.getUsername() == null || user.getUsername().isBlank() ? "user:" + userId : user.getUsername();
    }
}
