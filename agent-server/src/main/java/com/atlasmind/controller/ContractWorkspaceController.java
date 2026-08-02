package com.atlasmind.controller;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.common.Result;
import com.atlasmind.entity.User;
import com.atlasmind.service.ContractCaseService;
import com.atlasmind.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

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

    private String currentActor() {
        long userId = StpUtil.getLoginIdAsLong();
        User user = userService.getById(userId);
        if (user == null) return "user:" + userId;
        return user.getUsername() == null || user.getUsername().isBlank() ? "user:" + userId : user.getUsername();
    }
}
