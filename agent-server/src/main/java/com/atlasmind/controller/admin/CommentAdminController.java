package com.atlasmind.controller.admin;

import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.service.CommentService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * 后台评论管理（需登录）：评论列表审核、删除。
 * <p>
 * 评论状态通常为 0(待审)/1(通过)/2(垃圾)，通过 {@code PUT /{id}/status} 切换。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/comments")
public class CommentAdminController {

    private final CommentService commentService;

    @GetMapping
    public Result<Map<String, Object>> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(required = false) Integer status,
            @RequestParam(required = false) Integer type) {
        var pageResult = commentService.getAdminList(page, size, status, type);
        Map<String, Object> map = new HashMap<>();
        map.put("records", pageResult.getRecords());
        map.put("total", pageResult.getTotal());
        return Result.ok(map);
    }

    @OperationLog(value = "审核评论", type = "UPDATE")
    @PutMapping("/{id}/status")
    public Result<?> updateStatus(@PathVariable Long id, @RequestBody Map<String, Integer> body) {
        commentService.updateStatus(id, body.get("status"));
        return Result.ok();
    }

    @OperationLog(value = "删除评论", type = "DELETE")
    @DeleteMapping("/{id}")
    public Result<?> delete(@PathVariable Long id) {
        commentService.delete(id);
        return Result.ok();
    }
}
