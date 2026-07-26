package com.atlasmind.controller;

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
 * 前台评论接口（公开）：获取某篇文章的评论列表、发表评论。
 * <p>
 * 新评论默认 status=1（直接展示），可在后台标记为待审核。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/articles/{articleId}/comments")
public class CommentController {

    private final CommentService commentService;

    @GetMapping
    public Result<Map<String, Object>> list(@PathVariable Long articleId) {
        var comments = commentService.getByArticleId(articleId);
        Map<String, Object> map = new HashMap<>();
        map.put("records", comments);
        map.put("total", comments.size());
        return Result.ok(map);
    }

    @RateLimit(key = "comment", limit = 5, window = 60, message = "评论过于频繁，请 1 分钟后再试")
    @PostMapping
    public Result<Comment> create(@PathVariable Long articleId, @Valid @RequestBody CommentDto dto) {
        return Result.ok(commentService.create(articleId, dto));
    }
}
