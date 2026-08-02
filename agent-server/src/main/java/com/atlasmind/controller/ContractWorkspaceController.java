package com.atlasmind.controller;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.common.Result;
import com.atlasmind.entity.User;
import com.atlasmind.service.ContractCaseService;
import com.atlasmind.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * ContractOps workspace API — contract lifecycle management.
 *
 * <p>Activated when {@code PRODUCT_MODE=contract}.  Legacy project endpoints
 * remain available at /api/workspace/projects for rollback compatibility.
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/workspace/contracts")
public class ContractWorkspaceController {

    private final ContractCaseService contractCaseService;
    private final UserService userService;
    private final StringRedisTemplate redisTemplate;
    private final JdbcTemplate jdbcTemplate;

    private final ExecutorService sseExecutor = Executors.newCachedThreadPool(
            r -> new Thread(r, "sse-contract-progress"));

    @GetMapping("/portfolio")
    public Result<Map<String, Object>> portfolio() {
        return Result.ok(contractCaseService.portfolio());
    }

    @GetMapping
    public Result<List<Map<String, Object>>> list(@RequestParam(required = false) Map<String, Object> filters) {
        return Result.ok(contractCaseService.listCases(filters));
    }

    @PostMapping
    public Result<Map<String, Object>> create(@RequestBody Map<String, Object> request) {
        return Result.ok(contractCaseService.createCase(request));
    }

    @GetMapping("/{caseId}")
    public Result<Map<String, Object>> getCase(@PathVariable Long caseId) {
        return Result.ok(contractCaseService.getCase(caseId));
    }

    @PutMapping("/{caseId}")
    public Result<Map<String, Object>> update(@PathVariable Long caseId, @RequestBody Map<String, Object> request) {
        return Result.ok(contractCaseService.updateCase(caseId, request));
    }

    @PostMapping("/{caseId}/documents")
    public Result<Map<String, Object>> uploadDocument(@PathVariable Long caseId, @RequestBody Map<String, Object> request) {
        return Result.ok(contractCaseService.uploadDocument(caseId, request));
    }

    @GetMapping("/{caseId}/documents")
    public Result<List<Map<String, Object>>> documents(@PathVariable Long caseId) {
        return Result.ok(contractCaseService.listDocuments(caseId));
    }

    @PostMapping("/{caseId}/runs")
    public Result<Map<String, Object>> startRun(@PathVariable Long caseId, @RequestBody(required = false) Map<String, Object> request) {
        return Result.ok(contractCaseService.startRun(caseId, request == null ? Map.of() : request));
    }

    @GetMapping("/{caseId}/runs")
    public Result<List<Map<String, Object>>> runs(@PathVariable Long caseId) {
        return Result.ok(contractCaseService.listRuns(caseId));
    }

    @GetMapping("/runs/{runId}")
    public Result<Map<String, Object>> getRun(@PathVariable Long runId) {
        return Result.ok(contractCaseService.getRun(runId));
    }

    @PostMapping("/runs/{runId}/actions/{actionId}/approval")
    public Result<Map<String, Object>> approve(
            @PathVariable Long runId, @PathVariable Long actionId,
            @RequestBody(required = false) Map<String, Object> request) {
        return Result.ok(contractCaseService.approveAction(runId, actionId,
                request == null ? Map.of() : request, currentActor()));
    }

    // Obligations
    @GetMapping("/{caseId}/obligations")
    public Result<List<Map<String, Object>>> obligations(@PathVariable Long caseId) {
        return Result.ok(contractCaseService.listObligations(caseId));
    }

    @PostMapping("/{caseId}/obligations")
    public Result<Map<String, Object>> createObligation(@PathVariable Long caseId, @RequestBody Map<String, Object> request) {
        return Result.ok(contractCaseService.createObligation(caseId, request));
    }

    @PutMapping("/obligations/{obligationId}")
    public Result<Map<String, Object>> updateObligation(@PathVariable Long obligationId, @RequestBody Map<String, Object> request) {
        return Result.ok(contractCaseService.updateObligation(obligationId, request));
    }

    @PostMapping("/{caseId}/fulfillment-evidence")
    public Result<Map<String, Object>> uploadFulfillmentEvidence(@PathVariable Long caseId, @RequestBody Map<String, Object> request) {
        return Result.ok(contractCaseService.uploadFulfillmentEvidence(caseId, request));
    }

    @GetMapping("/reminders")
    public Result<List<Map<String, Object>>> reminders() {
        return Result.ok(contractCaseService.listReminders());
    }

    @SuppressWarnings("unchecked")
    @GetMapping("/memories/{memoryId}")
    public Result<Map<String, Object>> memory(@PathVariable Long memoryId) {
        Map<String, Object> row = jdbcTemplate.queryForMap(
                "SELECT id, memory_type AS memoryType, title, content FROM agent_project_memory WHERE id=?", memoryId);
        return Result.ok(row);
    }

    @GetMapping(value = "/runs/{runId}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamRun(@PathVariable Long runId) {
        SseEmitter emitter = new SseEmitter(300_000L);
        String channel = "run:" + runId + ":progress";
        sseExecutor.execute(() -> {
            final RedisConnection[] holder = new RedisConnection[1];
            try {
                holder[0] = redisTemplate.getConnectionFactory().getConnection();
                holder[0].subscribe((message, pattern) -> {
                    try {
                        String body = new String(message.getBody(), StandardCharsets.UTF_8);
                        emitter.send(SseEmitter.event().name("progress").data(body));
                    } catch (IOException e) {
                        try { holder[0].close(); } catch (Exception ignored) {}
                    }
                }, channel.getBytes(StandardCharsets.UTF_8));
                emitter.onCompletion(() -> { try { holder[0].close(); } catch (Exception ignored) {} });
                emitter.onTimeout(() -> { try { holder[0].close(); } catch (Exception ignored) {} });
            } catch (Exception e) {
                emitter.completeWithError(e);
                if (holder[0] != null) { try { holder[0].close(); } catch (Exception ignored) {} }
            }
        });
        return emitter;
    }

    private String currentActor() {
        long userId = StpUtil.getLoginIdAsLong();
        User user = userService.getById(userId);
        if (user == null) return "user:" + userId;
        return user.getUsername() == null || user.getUsername().isBlank() ? "user:" + userId : user.getUsername();
    }
}
