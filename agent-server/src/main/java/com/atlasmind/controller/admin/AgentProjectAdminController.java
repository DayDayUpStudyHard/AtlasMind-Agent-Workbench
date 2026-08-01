package com.atlasmind.controller.admin;

import com.atlasmind.common.Result;
import com.atlasmind.service.AgentProjectService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/projects")
public class AgentProjectAdminController {

    private final AgentProjectService agentProjectService;

    @GetMapping
    public Result<List<Map<String, Object>>> list() {
        return Result.ok(agentProjectService.listProjects());
    }

    @GetMapping("/{projectId}")
    public Result<Map<String, Object>> project(@PathVariable Long projectId) {
        return Result.ok(agentProjectService.getProject(projectId));
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

    @GetMapping("/runs")
    public Result<List<Map<String, Object>>> runs() {
        return Result.ok(agentProjectService.listAllRuns());
    }

    @GetMapping("/runs/{runId}")
    public Result<Map<String, Object>> run(@PathVariable Long runId) {
        return Result.ok(agentProjectService.getRun(runId));
    }

    @GetMapping("/reports")
    public Result<List<Map<String, Object>>> reports() {
        return Result.ok(agentProjectService.listReports());
    }

    @GetMapping("/actions")
    public Result<List<Map<String, Object>>> actions(@RequestParam(required = false) String status) {
        return Result.ok(agentProjectService.listActions(status));
    }

    @DeleteMapping("/runs/{runId}")
    public Result<?> deleteRun(@PathVariable Long runId) {
        agentProjectService.deleteRun(runId);
        return Result.ok();
    }

    @DeleteMapping("/reports/{reportId}")
    public Result<?> deleteReport(@PathVariable Long reportId) {
        agentProjectService.deleteReport(reportId);
        return Result.ok();
    }

    @DeleteMapping("/actions/{actionId}")
    public Result<?> deleteAction(@PathVariable Long actionId) {
        agentProjectService.deleteAction(actionId);
        return Result.ok();
    }
}
