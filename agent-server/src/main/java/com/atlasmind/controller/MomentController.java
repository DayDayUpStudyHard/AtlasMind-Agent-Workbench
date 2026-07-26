package com.atlasmind.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.common.Result;
import com.atlasmind.entity.Moment;
import com.atlasmind.service.MomentService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * 公开说说接口：分页查看说说列表。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/moments")
public class MomentController {

    private final MomentService momentService;

    @GetMapping
    public Result<Map<String, Object>> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size) {
        Page<Moment> pageResult = momentService.list(page, size);
        Map<String, Object> map = new HashMap<>();
        map.put("records", pageResult.getRecords());
        map.put("total", pageResult.getTotal());
        return Result.ok(map);
    }
}
