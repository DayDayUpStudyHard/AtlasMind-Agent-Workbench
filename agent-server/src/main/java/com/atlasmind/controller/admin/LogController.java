package com.atlasmind.controller.admin;

import com.atlasmind.common.Result;
import com.atlasmind.service.OperationLogService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * 操作日志管理控制器 — 提供审计日志的分页查询，仅管理员可访问。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/logs")
public class LogController {

    private final OperationLogService operationLogService;

    @GetMapping
    public Result<Map<String, Object>> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(required = false) String type) {
        var pageResult = operationLogService.getList(page, size, type);
        Map<String, Object> map = new HashMap<>();
        map.put("records", pageResult.getRecords());
        map.put("total", pageResult.getTotal());
        return Result.ok(map);
    }
}
