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

    private String normalizeKeyword(String keyword) {
        if (keyword == null || keyword.isBlank()) return null;
        return keyword.trim();
    }
}
