package com.atlasmind.controller;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.dto.StoreResult;
import com.atlasmind.entity.User;
import com.atlasmind.service.ContractAccessPolicy;
import com.atlasmind.service.ContractCaseService;
import com.atlasmind.service.ContractMemberService;
import com.atlasmind.service.FileStorageService;
import com.atlasmind.service.PrivateUploadService;
import com.atlasmind.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.CacheControl;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
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
    private final ContractAccessPolicy accessPolicy;
    private final ContractMemberService contractMemberService;
    private final FileStorageService fileStorageService;
    private final UserService userService;
    private final StringRedisTemplate redisTemplate;
    private final JdbcTemplate jdbcTemplate;
    private final PrivateUploadService privateUploadService;

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

    @GetMapping("/document-pipelines/recent")
    public Result<List<Map<String, Object>>> recentDocumentPipelines() {
        return Result.ok(contractCaseService.listRecentDocumentPipelines());
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
        privateUploadService.register(stored.getUrl(), StpUtil.getLoginIdAsLong(),
                file.getOriginalFilename(), file.getContentType());
        privateUploadService.register(stored.getThumbUrl(), StpUtil.getLoginIdAsLong(),
                file.getOriginalFilename(), file.getContentType());
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
        accessPolicy.checkAccess(caseId);
        return Result.ok(contractCaseService.getCase(caseId));
    }

    @PutMapping("/{caseId}")
    public Result<Map<String, Object>> update(@PathVariable Long caseId, @RequestBody Map<String, Object> request) {
        accessPolicy.checkWriteAccess(caseId);
        return Result.ok(contractCaseService.updateCase(caseId, request));
    }

    @PostMapping("/{caseId}/documents")
    public Result<Map<String, Object>> uploadDocument(@PathVariable Long caseId, @RequestBody Map<String, Object> request) {
        accessPolicy.checkWriteAccess(caseId);
        return Result.ok(contractCaseService.uploadDocument(caseId, request));
    }

    @GetMapping("/{caseId}/documents")
    public Result<List<Map<String, Object>>> documents(@PathVariable Long caseId) {
        accessPolicy.checkAccess(caseId);
        return Result.ok(contractCaseService.listDocuments(caseId));
    }

    @GetMapping("/{caseId}/documents/{documentId}/content")
    public Result<Map<String, Object>> documentContent(
            @PathVariable Long caseId, @PathVariable Long documentId) {
        accessPolicy.checkAccess(caseId);
        return Result.ok(contractCaseService.getDocumentContent(caseId, documentId));
    }

    /**
     * 鉴权文件下载 — 所有文件访问的规范入口。
     * 流程：定位文件 → 定位合同 → 校验合同权限 → 校验文件状态 → 记录访问日志 → 返回流。
     * 读不到和无权限统一返回 404。
     */
    @GetMapping("/documents/{documentId}/download")
    public ResponseEntity<org.springframework.core.io.Resource> downloadDocument(
            @PathVariable Long documentId) {
        PrivateUploadService.PrivateFile file = contractCaseService.downloadDocument(documentId);
        MediaType mediaType;
        try {
            mediaType = file.contentType() == null
                    ? MediaType.APPLICATION_OCTET_STREAM
                    : MediaType.parseMediaType(file.contentType());
        } catch (Exception ignored) {
            mediaType = MediaType.APPLICATION_OCTET_STREAM;
        }
        boolean inline = MediaType.APPLICATION_PDF.includes(mediaType)
                || "image".equalsIgnoreCase(mediaType.getType());
        ContentDisposition disposition = (inline
                ? ContentDisposition.inline()
                : ContentDisposition.attachment())
                .filename(file.fileName(), StandardCharsets.UTF_8)
                .build();
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .header(HttpHeaders.CONTENT_DISPOSITION, disposition.toString())
                .header("X-Content-Type-Options", "nosniff")
                .contentType(mediaType)
                .body(file.resource());
    }

    @PostMapping("/{caseId}/runs")
    public Result<Map<String, Object>> startRun(@PathVariable Long caseId, @RequestBody(required = false) Map<String, Object> request) {
        accessPolicy.checkWriteAccess(caseId);
        return Result.ok(contractCaseService.startRun(caseId, request == null ? Map.of() : request));
    }

    @GetMapping("/{caseId}/runs")
    public Result<List<Map<String, Object>>> runs(@PathVariable Long caseId) {
        accessPolicy.checkAccess(caseId);
        return Result.ok(contractCaseService.listRuns(caseId));
    }

    @GetMapping("/runs/{runId}")
    public Result<Map<String, Object>> getRun(@PathVariable Long runId) {
        Map<String, Object> run = contractCaseService.getRun(runId);
        if (run != null && run.get("subjectId") instanceof Number sid) {
            accessPolicy.checkAccess(sid.longValue());
        }
        return Result.ok(run);
    }

    @PatchMapping("/findings/{findingId}")
    public Result<Map<String, Object>> updateFinding(
            @PathVariable Long findingId,
            @RequestBody(required = false) Map<String, Object> request) {
        // Resolve case ID from finding and check access
        Long caseId = jdbcTemplate.queryForObject(
            "SELECT case_id FROM contract_review_finding WHERE id=?", Long.class, findingId);
        if (caseId != null) accessPolicy.checkReviewAccess(caseId);
        return Result.ok(contractCaseService.updateFinding(
                findingId, request == null ? Map.of() : request));
    }

    @PatchMapping("/{caseId}/elements/{elementId}/review")
    @OperationLog(value = "人工审核合同要素", type = "UPDATE")
    public Result<Map<String, Object>> reviewContractElement(
            @PathVariable Long caseId,
            @PathVariable Long elementId,
            @RequestBody(required = false) Map<String, Object> request) {
        accessPolicy.checkReviewAccess(caseId);
        return Result.ok(contractCaseService.reviewContractElement(
                caseId, elementId, request == null ? Map.of() : request, currentActor()));
    }

    @PatchMapping("/{caseId}/facts/review")
    @OperationLog(value = "人工审核合同事实", type = "UPDATE")
    public Result<Map<String, Object>> reviewContractFact(
            @PathVariable Long caseId,
            @RequestBody(required = false) Map<String, Object> request) {
        accessPolicy.checkReviewAccess(caseId);
        return Result.ok(contractCaseService.reviewContractFact(
                caseId, request == null ? Map.of() : request, currentActor()));
    }

    @PostMapping("/runs/{runId}/actions/{actionId}/approval")
    public Result<Map<String, Object>> approve(
            @PathVariable Long runId, @PathVariable Long actionId,
            @RequestBody(required = false) Map<String, Object> request) {
        Map<String, Object> run = contractCaseService.getRun(runId);
        if (run != null && run.get("subjectId") instanceof Number sid) {
            accessPolicy.checkReviewAccess(sid.longValue());
        }
        return Result.ok(contractCaseService.approveAction(runId, actionId,
                request == null ? Map.of() : request, currentActor()));
    }

    @PostMapping("/{caseId}/timeline/{timelineNodeId}/fulfillment-checks")
    @OperationLog(value = "发起合同履约核验", type = "CREATE")
    public Result<Map<String, Object>> startTimelineFulfillmentCheck(
            @PathVariable Long caseId, @PathVariable Long timelineNodeId) {
        accessPolicy.checkWriteAccess(caseId);
        return Result.ok(contractCaseService.startTimelineFulfillmentCheck(caseId, timelineNodeId));
    }

    @PatchMapping("/{caseId}/timeline/{timelineNodeId}/review")
    @OperationLog(value = "人工审核合同时间节点", type = "UPDATE")
    public Result<Map<String, Object>> reviewTimelineNode(
            @PathVariable Long caseId,
            @PathVariable Long timelineNodeId,
            @RequestBody(required = false) Map<String, Object> request) {
        accessPolicy.checkReviewAccess(caseId);
        return Result.ok(contractCaseService.reviewTimelineNode(
                caseId, timelineNodeId, request == null ? Map.of() : request, currentActor()));
    }

    @PatchMapping("/fulfillment-checks/{checkId}/confirmation")
    @OperationLog(value = "人工确认合同履约核验", type = "UPDATE")
    public Result<Map<String, Object>> confirmFulfillmentCheck(
            @PathVariable Long checkId,
            @RequestBody(required = false) Map<String, Object> request) {
        Long caseId = jdbcTemplate.queryForObject(
            "SELECT case_id FROM contract_fulfillment_check WHERE id=?", Long.class, checkId);
        if (caseId != null) accessPolicy.checkAccess(caseId);
        return Result.ok(contractCaseService.confirmFulfillmentCheck(
                checkId, request == null ? Map.of() : request, currentActor()));
    }

    @GetMapping("/{caseId}/timeline/{timelineNodeId}/evidence-links")
    public Result<Map<String, Object>> timelineEvidenceLinks(
            @PathVariable Long caseId, @PathVariable Long timelineNodeId) {
        accessPolicy.checkAccess(caseId);
        return Result.ok(contractCaseService.getTimelineEvidenceLinks(caseId, timelineNodeId));
    }

    @PutMapping("/{caseId}/timeline/{timelineNodeId}/evidence-links")
    @OperationLog(value = "调整合同时间节点证据", type = "UPDATE")
    public Result<Map<String, Object>> saveTimelineEvidenceLinks(
            @PathVariable Long caseId, @PathVariable Long timelineNodeId,
            @RequestBody(required = false) Map<String, Object> request) {
        accessPolicy.checkWriteAccess(caseId);
        return Result.ok(contractCaseService.saveTimelineEvidenceLinks(
                caseId, timelineNodeId, request == null ? Map.of() : request));
    }

    // Obligations
    @GetMapping("/{caseId}/obligations")
    public Result<List<Map<String, Object>>> obligations(@PathVariable Long caseId) {
        accessPolicy.checkAccess(caseId);
        return Result.ok(contractCaseService.listObligations(caseId));
    }

    @PostMapping("/{caseId}/obligations")
    public Result<Map<String, Object>> createObligation(@PathVariable Long caseId, @RequestBody Map<String, Object> request) {
        accessPolicy.checkWriteAccess(caseId);
        return Result.ok(contractCaseService.createObligation(caseId, request));
    }

    @PutMapping("/obligations/{obligationId}")
    public Result<Map<String, Object>> updateObligation(@PathVariable Long obligationId, @RequestBody Map<String, Object> request) {
        Long caseId = jdbcTemplate.queryForObject(
            "SELECT case_id FROM contract_obligation WHERE id=?", Long.class, obligationId);
        if (caseId != null) accessPolicy.checkWriteAccess(caseId);
        return Result.ok(contractCaseService.updateObligation(obligationId, request));
    }

    @PostMapping("/{caseId}/fulfillment-evidence")
    @OperationLog(value = "上传合同履约证据", type = "CREATE")
    public Result<Map<String, Object>> uploadFulfillmentEvidence(@PathVariable Long caseId, @RequestBody Map<String, Object> request) {
        accessPolicy.checkWriteAccess(caseId);
        return Result.ok(contractCaseService.uploadFulfillmentEvidence(caseId, request));
    }

    // ── 状态转换 ──────────────────────────────────────────────────

    @PostMapping("/{caseId}/submit-review")
    @OperationLog(value = "提交审核", type = "UPDATE")
    public Result<Map<String, Object>> submitReview(@PathVariable Long caseId) {
        accessPolicy.checkWriteAccess(caseId);
        contractCaseService.transitionStatus(caseId, "READY_FOR_REVIEW", "REVIEWING", null,
                StpUtil.getLoginIdAsLong());
        return Result.ok(Map.of("status", "REVIEWING"));
    }

    @PostMapping("/{caseId}/approve")
    @OperationLog(value = "审批通过", type = "UPDATE")
    public Result<Map<String, Object>> approve(@PathVariable Long caseId) {
        accessPolicy.checkReviewAccess(caseId);
        contractCaseService.transitionStatus(caseId, "PENDING_APPROVAL", "APPROVED", null,
                StpUtil.getLoginIdAsLong());
        return Result.ok(Map.of("status", "APPROVED"));
    }

    @PostMapping("/{caseId}/request-revision")
    @OperationLog(value = "要求修订", type = "UPDATE")
    public Result<Map<String, Object>> requestRevision(@PathVariable Long caseId,
                                                       @RequestBody Map<String, Object> body) {
        accessPolicy.checkReviewAccess(caseId);
        String reason = str(body, "reason");
        contractCaseService.transitionStatus(caseId, "PENDING_APPROVAL", "NEEDS_REVISION", reason,
                StpUtil.getLoginIdAsLong());
        return Result.ok(Map.of("status", "NEEDS_REVISION"));
    }

    // ── 成员管理 ──────────────────────────────────────────────────

    @GetMapping("/{caseId}/members")
    public Result<List<Map<String, Object>>> listMembers(@PathVariable Long caseId) {
        accessPolicy.checkAccess(caseId);
        return Result.ok(contractMemberService.listMembers(caseId));
    }

    @PostMapping("/{caseId}/members/invite")
    @OperationLog(value = "邀请合同成员", type = "CREATE")
    public Result<Map<String, Object>> inviteMember(@PathVariable Long caseId,
                                                    @RequestBody Map<String, Object> body) {
        accessPolicy.checkManageMembersAccess(caseId);
        Long userId = toLong(body.get("userId"));
        String role = str(body, "role");
        contractMemberService.inviteMember(caseId, userId, role, StpUtil.getLoginIdAsLong());
        return Result.ok(Map.of("invited", true));
    }

    @PatchMapping("/{caseId}/members/{userId}")
    @OperationLog(value = "更新合同成员角色", type = "UPDATE")
    public Result<Map<String, Object>> updateMemberRole(@PathVariable Long caseId,
                                                        @PathVariable Long userId,
                                                        @RequestBody Map<String, Object> body) {
        accessPolicy.checkManageMembersAccess(caseId);
        String role = str(body, "role");
        contractMemberService.updateMemberRole(caseId, userId, role, StpUtil.getLoginIdAsLong());
        return Result.ok(Map.of("updated", true));
    }

    @DeleteMapping("/{caseId}/members/{userId}")
    @OperationLog(value = "移除合同成员", type = "DELETE")
    public Result<Map<String, Object>> removeMember(@PathVariable Long caseId,
                                                    @PathVariable Long userId) {
        accessPolicy.checkManageMembersAccess(caseId);
        contractMemberService.removeMember(caseId, userId, StpUtil.getLoginIdAsLong());
        return Result.ok(Map.of("removed", true));
    }

    @PostMapping("/{caseId}/owner/transfer")
    @OperationLog(value = "转移合同负责人", type = "UPDATE")
    public Result<Map<String, Object>> transferOwnership(@PathVariable Long caseId,
                                                         @RequestBody Map<String, Object> body) {
        Long newOwnerId = toLong(body.get("userId"));
        contractMemberService.transferOwnership(caseId, newOwnerId, StpUtil.getLoginIdAsLong());
        return Result.ok(Map.of("transferred", true));
    }

    @GetMapping("/reminders")
    public Result<List<Map<String, Object>>> reminders() {
        return Result.ok(contractCaseService.listReminders());
    }

    @SuppressWarnings("unchecked")
    @GetMapping("/memories/{memoryId}")
    public Result<Map<String, Object>> memory(@PathVariable Long memoryId) {
        Map<String, Object> row = jdbcTemplate.queryForMap(
                "SELECT id, memory_type AS memoryType, title, content, project_id FROM agent_project_memory WHERE id=?", memoryId);
        // Check contract access: project_id references contract_case.id in contract mode
        Object pid = row.get("project_id");
        if (pid instanceof Number) {
            accessPolicy.checkAccess(((Number) pid).longValue());
        }
        return Result.ok(row);
    }

    @GetMapping(value = "/runs/{runId}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamRun(@PathVariable Long runId) {
        // Check contract access before subscribing to SSE stream
        Map<String, Object> run = contractCaseService.getRun(runId);
        if (run != null && run.get("subjectId") instanceof Number sid) {
            accessPolicy.checkAccess(sid.longValue());
        }

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

    private String str(Map<String, Object> m, String k) {
        Object v = m == null ? null : m.get(k);
        return v == null ? "" : String.valueOf(v);
    }

    private Long toLong(Object val) {
        if (val instanceof Number n) return n.longValue();
        if (val instanceof String s && !s.isBlank()) {
            try { return Long.parseLong(s); } catch (NumberFormatException e) { return null; }
        }
        return null;
    }
}
