package com.atlasmind.controller.admin;

import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.entity.Tag;
import com.atlasmind.service.TagService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

/**
 * 后台标签管理（需登录）：创建、更新、删除标签。
 * <p>
 * 注意：更新时手动将路径参数 id 设入 Tag 对象，确保 MyBatis-Plus 按 id 更新。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/tags")
public class TagAdminController {

    private final TagService tagService;

    @OperationLog(value = "创建标签", type = "CREATE")
    @PostMapping
    public Result<Tag> create(@Valid @RequestBody Tag tag) {
        return Result.ok(tagService.create(tag));
    }

    @OperationLog(value = "更新标签", type = "UPDATE")
    @PutMapping("/{id}")
    public Result<Tag> update(@PathVariable Long id, @Valid @RequestBody Tag tag) {
        tag.setId(id);
        return Result.ok(tagService.update(tag));
    }

    @OperationLog(value = "删除标签", type = "DELETE")
    @DeleteMapping("/{id}")
    public Result<?> delete(@PathVariable Long id) {
        tagService.delete(id);
        return Result.ok();
    }
}
