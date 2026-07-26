package com.atlasmind.controller.admin;

import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.dto.ArticleDto;
import com.atlasmind.entity.Article;
import com.atlasmind.service.ArticleService;
import com.atlasmind.service.TagService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * 后台文章管理（需登录）：CRUD 文章。
 * <p>
 * 重点：创建/更新文章时同步维护 {@code t_article_tag} 关联表；
 * 删除时同时清理关联数据，保持数据一致性。事务由 {@code ArticleServiceImpl} 管理。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/articles")
public class ArticleAdminController {

    private final ArticleService articleService;
    private final TagService tagService;

    @GetMapping
    public Result<Map<String, Object>> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(required = false) Integer status,
            @RequestParam(required = false) String visibility) {
        var pageResult = articleService.getAdminList(page, size, status, visibility);
        Map<String, Object> map = new HashMap<>();
        map.put("records", pageResult.getRecords());
        map.put("total", pageResult.getTotal());
        return Result.ok(map);
    }

    @GetMapping("/{id}")
    public Result<Article> detail(@PathVariable Long id) {
        Article article = articleService.getById(id);
        if (article != null) {
            article.setTags(tagService.getByArticleId(id));
        }
        return Result.ok(article);
    }

    @OperationLog(value = "创建文章", type = "CREATE")
    @PostMapping
    public Result<Article> create(@Valid @RequestBody ArticleDto dto) {
        return Result.ok(articleService.create(dto));
    }

    @OperationLog(value = "更新文章", type = "UPDATE")
    @PutMapping("/{id}")
    public Result<Article> update(@PathVariable Long id, @Valid @RequestBody ArticleDto dto) {
        return Result.ok(articleService.update(id, dto));
    }

    @OperationLog(value = "删除文章", type = "DELETE")
    @DeleteMapping("/{id}")
    public Result<?> delete(@PathVariable Long id) {
        articleService.delete(id);
        return Result.ok();
    }
}
