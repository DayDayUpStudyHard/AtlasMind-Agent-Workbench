package com.atlasmind.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.common.Result;
import com.atlasmind.entity.Article;
import com.atlasmind.entity.Tag;
import com.atlasmind.service.ArticleLikeService;
import com.atlasmind.service.ArticleService;
import com.atlasmind.service.TagService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 前台文章接口（无需登录）：文章列表、详情、上下篇导航、点赞、搜索。
 * <p>
 * 列表仅返回已发布(status=1)的文章；详情页会自增阅读量。
 * 列表接口返回 {@code content} 字段为空以减少传输量，详情接口返回完整内容。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/articles")
public class ArticleController {

    private final ArticleService articleService;
    private final TagService tagService;
    private final ArticleLikeService articleLikeService;

    @GetMapping
    public Result<Map<String, Object>> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(required = false) Long categoryId,
            @RequestParam(required = false) String keyword) {
        Page<Article> pageResult = articleService.getPublishedList(page, size, categoryId, keyword);
        Map<String, Object> map = new HashMap<>();
        map.put("records", pageResult.getRecords());
        map.put("total", pageResult.getTotal());
        return Result.ok(map);
    }

    @GetMapping("/archive")
    public Result<List<Map<String, Object>>> archive() {
        return Result.ok(articleService.getArchive());
    }

    @GetMapping("/{id}")
    public Result<Article> detail(@PathVariable Long id) {
        Article article = articleService.getDetail(id);
        return Result.ok(article);
    }

    @GetMapping("/{id}/nav")
    public Result<Map<String, Object>> nav(@PathVariable Long id) {
        return Result.ok(articleService.getNav(id));
    }

    // ==================== 点赞 ====================

    @PostMapping("/{id}/like")
    public Result<Map<String, Object>> toggleLike(@PathVariable Long id, HttpServletRequest request) {
        String ip = getClientIp(request);
        return Result.ok(articleLikeService.toggle(id, ip));
    }

    @GetMapping("/{id}/likes")
    public Result<Map<String, Object>> getLikes(@PathVariable Long id, HttpServletRequest request) {
        String ip = getClientIp(request);
        return Result.ok(articleLikeService.getLikeInfo(id, ip));
    }

    @GetMapping("/top")
    public Result<List<Map<String, Object>>> topArticles(
            @RequestParam(defaultValue = "10") int limit) {
        return Result.ok(articleLikeService.getTopLiked(Math.min(limit, 50)));
    }

    // ==================== 全文搜索 ====================

    @GetMapping("/search")
    public Result<Map<String, Object>> search(
            @RequestParam String keyword,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size) {
        // 委托给 ArticleService（内部调用 ES 搜索服务）
        Page<Article> pageResult = articleService.search(keyword, page, size);
        Map<String, Object> map = new HashMap<>();
        map.put("records", pageResult.getRecords());
        map.put("total", pageResult.getTotal());
        return Result.ok(map);
    }

    /**
     * 获取客户端真实 IP，优先取 X-Forwarded-For 的第一个 IP。
     */
    private String getClientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            return forwarded.split(",")[0].trim();
        }
        String realIp = request.getHeader("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) {
            return realIp.trim();
        }
        return request.getRemoteAddr();
    }
}
