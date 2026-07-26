package com.atlasmind.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.annotation.RateLimit;
import com.atlasmind.common.Result;
import com.atlasmind.dto.CommentDto;
import com.atlasmind.entity.Comment;
import com.atlasmind.service.CommentService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * 公开留言板接口：列表查询 + 提交留言。
 * <p>
 * 复用 {@code t_comment} 表，article_id 为 NULL 表示留言板留言。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/guestbook")
public class GuestbookController {

    private final CommentService commentService;

    @GetMapping
    public Result<Map<String, Object>> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size) {
        Page<Comment> pageResult = commentService.getGuestbookList(page, size);
        Map<String, Object> map = new HashMap<>();
        map.put("records", pageResult.getRecords());
        map.put("total", pageResult.getTotal());
        return Result.ok(map);
    }

    @RateLimit(key = "guestbook", limit = 3, window = 60, message = "留言过于频繁，请 1 分钟后再试")
    @PostMapping
    public Result<Comment> create(@Valid @RequestBody CommentDto dto) {
        return Result.ok(commentService.createGuestbook(dto));
    }
}
