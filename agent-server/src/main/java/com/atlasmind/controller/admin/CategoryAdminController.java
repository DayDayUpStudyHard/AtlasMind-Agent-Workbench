package com.atlasmind.controller.admin;

import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.entity.Category;
import com.atlasmind.service.CategoryService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

/**
 * 后台分类管理（需登录）：创建、更新、删除分类。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/categories")
public class CategoryAdminController {

    private final CategoryService categoryService;

    @OperationLog(value = "创建分类", type = "CREATE")
    @PostMapping
    public Result<Category> create(@Valid @RequestBody Category category) {
        return Result.ok(categoryService.create(category));
    }

    @OperationLog(value = "更新分类", type = "UPDATE")
    @PutMapping("/{id}")
    public Result<Category> update(@PathVariable Long id, @Valid @RequestBody Category category) {
        return Result.ok(categoryService.update(id, category));
    }

    @OperationLog(value = "删除分类", type = "DELETE")
    @DeleteMapping("/{id}")
    public Result<?> delete(@PathVariable Long id) {
        categoryService.delete(id);
        return Result.ok();
    }
}
