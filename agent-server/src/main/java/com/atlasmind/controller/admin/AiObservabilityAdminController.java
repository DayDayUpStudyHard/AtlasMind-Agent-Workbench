package com.atlasmind.controller.admin;

import com.atlasmind.common.Result;
import com.atlasmind.mapper.AiObservabilityMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/ai-observability")
public class AiObservabilityAdminController {

    private final AiObservabilityMapper observabilityMapper;

    @GetMapping("/traces")
    public Result<Map<String, Object>> traces(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String keyword) {
        long safePage = Math.max(1, page);
        long safeSize = Math.max(1, Math.min(size, 50));
        long offset = (safePage - 1) * safeSize;
        observabilityMapper.ensureToolCallTable();

        Map<String, Object> data = new HashMap<>();
        data.put("records", observabilityMapper.listTraces(offset, safeSize, normalizeKeyword(keyword)));
        data.put("total", observabilityMapper.countTraces(normalizeKeyword(keyword)));
        return Result.ok(data);
    }

    @GetMapping("/traces/{id}")
    public Result<Map<String, Object>> trace(@PathVariable Long id) {
        observabilityMapper.ensureToolCallTable();
        Map<String, Object> trace = observabilityMapper.getTrace(id);
        if (trace == null) {
            return Result.fail("Trace not found");
        }
        trace.put("hits", observabilityMapper.listHits(id));
        trace.put("toolCalls", observabilityMapper.listToolCalls(id));
        return Result.ok(trace);
    }

    @GetMapping("/agent-runs")
    public Result<Map<String, Object>> agentRuns(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String subjectType,
            @RequestParam(required = false) String runType,
            @RequestParam(required = false) String status) {
        long safePage = Math.max(1, page);
        long safeSize = Math.max(1, Math.min(size, 50));
        long offset = (safePage - 1) * safeSize;

        Map<String, Object> data = new HashMap<>();
        data.put("records", observabilityMapper.listAgentRuns(
                offset, safeSize, normalizeKeyword(keyword),
                normalizeEnum(subjectType), normalizeEnum(runType), normalizeEnum(status)));
        data.put("total", observabilityMapper.countAgentRuns(
                normalizeKeyword(keyword), normalizeEnum(subjectType),
                normalizeEnum(runType), normalizeEnum(status)));
        return Result.ok(data);
    }

    @GetMapping("/agent-runs/{id}")
    public Result<Map<String, Object>> agentRun(@PathVariable Long id) {
        Map<String, Object> run = observabilityMapper.getAgentRun(id);
        if (run == null) {
            return Result.fail("Agent Run not found");
        }
        Map<String, Object> data = new HashMap<>(run);
        data.put("traces", observabilityMapper.listAgentRunTraces(id));
        data.put("toolCalls", observabilityMapper.listAgentRunToolCalls(id));
        data.put("reports", observabilityMapper.listAgentRunReports(id));
        data.put("findings", observabilityMapper.listAgentRunFindings(id));
        data.put("actions", observabilityMapper.listAgentRunActions(id));
        return Result.ok(data);
    }

    @GetMapping("/document-pipelines")
    public Result<Map<String, Object>> documentPipelines(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String status) {
        long safePage = Math.max(1, page);
        long safeSize = Math.max(1, Math.min(size, 50));
        long offset = (safePage - 1) * safeSize;

        Map<String, Object> data = new HashMap<>();
        data.put("records", observabilityMapper.listDocumentPipelines(
                offset, safeSize, normalizeKeyword(keyword), normalizeEnum(status)));
        data.put("total", observabilityMapper.countDocumentPipelines(
                normalizeKeyword(keyword), normalizeEnum(status)));
        return Result.ok(data);
    }

    @GetMapping("/document-pipelines/{id}")
    public Result<Map<String, Object>> documentPipeline(@PathVariable Long id) {
        Map<String, Object> pipeline = observabilityMapper.getDocumentPipeline(id);
        if (pipeline == null) {
            return Result.fail("Document Pipeline not found");
        }
        Map<String, Object> data = new HashMap<>(pipeline);
        data.put("traces", observabilityMapper.listDocumentPipelineTraces(id));
        return Result.ok(data);
    }

    private String normalizeKeyword(String keyword) {
        if (keyword == null || keyword.isBlank()) return null;
        return keyword.trim();
    }

    private String normalizeEnum(String value) {
        if (value == null || value.isBlank()) return null;
        return value.trim().toUpperCase();
    }
}
