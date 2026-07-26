package com.atlasmind.controller;

import com.atlasmind.common.Result;
import com.atlasmind.entity.Category;
import com.atlasmind.service.CategoryService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 前台分类接口（公开）：返回所有分类列表。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/categories")
public class CategoryController {

    private final CategoryService categoryService;

    @GetMapping
    public Result<List<Category>> list() {
        return Result.ok(categoryService.list());
    }
}
