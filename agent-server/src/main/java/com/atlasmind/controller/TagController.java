package com.atlasmind.controller;

import com.atlasmind.common.Result;
import com.atlasmind.entity.Tag;
import com.atlasmind.service.TagService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 前台标签接口（公开）：返回所有标签列表。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/tags")
public class TagController {

    private final TagService tagService;

    @GetMapping
    public Result<List<Tag>> list() {
        return Result.ok(tagService.list());
    }
}
