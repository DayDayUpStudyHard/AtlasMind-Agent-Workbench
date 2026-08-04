package com.atlasmind.controller;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.common.Result;
import com.atlasmind.dto.StoreResult;
import com.atlasmind.entity.User;
import com.atlasmind.service.ContractCaseService;
import com.atlasmind.service.FileStorageService;
import com.atlasmind.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
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
    private final FileStorageService fileStorageService;
    private final UserService userService;
    private final StringRedisTemplate redisTemplate;
    private final JdbcTemplate jdbcTemplate;

    private final ExecutorService sseExecutor = Executors.newCachedThreadPool(
            r -> new Thread(r, "sse-contract-progress"));

    @GetMapping("/portfolio")
    public Result<Map<String, Object>> portfolio() {
        return Result.ok(contractCaseService.portfolio());
    }

    @GetMapping("/work-queues/summary")
    public Result<Map<String, Object>> workQueueSummary() {
        return Result.ok(contractCaseService.workQueueSummary());
    }

    @GetMapping("/work-queues")
    public Result<List<Map<String, Object>>> workQueue(@RequestParam(defaultValue = "REVIEW") String type) {
        return Result.ok(contractCaseService.listWorkQueue(type));
    }

    @GetMapping
    public Result<List<Map<String, Object>>> list(@RequestParam(required = false) Map<String, Object> filters) {
        return Result.ok(contractCaseService.listCases(filters));
    }

    @PostMapping
    public Result<Map<String, Object>> create(@RequestBody Map<String, Object> request) {
        return Result.ok(contractCaseService.createCase(request));
    }

    @PostMapping("/intakes")
    public Result<Map<String, Object>> createIntake(@RequestBody Map<String, Object> request) {
        return Result.ok(contractCaseService.createIntake(request, StpUtil.getLoginIdAsLong()));
    }

    @PostMapping(value = "/intakes/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Result<Map<String, Object>> createFileIntake(@RequestParam("file") MultipartFile file)
            throws IOException {
        StoreResult stored = fileStorageService.store(file);
        return Result.ok(contractCaseService.createFileIntake(Map.of(
                "fileName", file.getOriginalFilename() == null ? "" : file.getOriginalFilename(),
                "filePath", stored.getUrl(),
                "fileSize", file.getSize()
        ), StpUtil.getLoginIdAsLong()));
    }

    @GetMapping("/intakes/{intakeId}")
    public Result<Map<String, Object>> getIntake(@PathVariable Long intakeId) {
        return Result.ok(contractCaseService.getIntake(intakeId, StpUtil.getLoginIdAsLong()));
    }

    @PostMapping("/intakes/{intakeId}/retry")
    public Result<Map<String, Object>> retryIntake(@PathVariable Long intakeId) {
        return Result.ok(contractCaseService.retryIntake(intakeId, StpUtil.getLoginIdAsLong()));
    }

    @PostMapping("/intakes/{intakeId}/confirm")
    public Result<Map<String, Object>> confirmIntake(
            @PathVariable Long intakeId, @RequestBody Map<String, Object> request) {
        return Result.ok(contractCaseService.confirmIntake(
                intakeId, request, StpUtil.getLoginIdAsLong()));
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

    @GetMapping("/{caseId}/documents/{documentId}/content")
    public Result<Map<String, Object>> documentContent(
            @PathVariable Long caseId, @PathVariable Long documentId) {
        return Result.ok(contractCaseService.getDocumentContent(caseId, documentId));
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

    @PatchMapping("/findings/{findingId}")
    public Result<Map<String, Object>> updateFinding(
            @PathVariable Long findingId,
            @RequestBody(required = false) Map<String, Object> request) {
        return Result.ok(contractCaseService.updateFinding(
                findingId, request == null ? Map.of() : request));
    }

    @PostMapping("/runs/{runId}/actions/{actionId}/approval")
    public Result<Map<String, Object>> approve(
            @PathVariable Long runId, @PathVariable Long actionId,
            @RequestBody(required = false) Map<String, Object> request) {
        return Result.ok(contractCaseService.approveAction(runId, actionId,
                request == null ? Map.of() : request, currentActor()));
    }

    @PostMapping("/{caseId}/timeline/{timelineNodeId}/fulfillment-checks")
    public Result<Map<String, Object>> startTimelineFulfillmentCheck(
            @PathVariable Long caseId, @PathVariable Long timelineNodeId) {
        return Result.ok(contractCaseService.startTimelineFulfillmentCheck(caseId, timelineNodeId));
    }

    @PatchMapping("/fulfillment-checks/{checkId}/confirmation")
    public Result<Map<String, Object>> confirmFulfillmentCheck(
            @PathVariable Long checkId,
            @RequestBody(required = false) Map<String, Object> request) {
        return Result.ok(contractCaseService.confirmFulfillmentCheck(
                checkId, request == null ? Map.of() : request, currentActor()));
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
