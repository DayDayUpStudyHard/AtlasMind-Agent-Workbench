package com.atlasmind.controller;

import com.atlasmind.common.Result;
import com.atlasmind.service.AgentProjectService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 项目总览、Agent Run、报告和审批入口。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/projects")
public class AgentWorkbenchController {

    private final AgentProjectService agentProjectService;

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
        return Result.ok(agentProjectService.approveAction(runId, actionId, request == null ? Map.of() : request));
    }

    @PostMapping("/runs/{runId}/actions/{actionId}/execute")
    public Result<Map<String, Object>> execute(
            @PathVariable Long runId,
            @PathVariable Long actionId) {
        return Result.ok(agentProjectService.executeAction(runId, actionId));
    }
}
