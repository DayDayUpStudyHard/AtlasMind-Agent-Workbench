package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.dto.ArticleDto;
import com.atlasmind.entity.Article;
import com.atlasmind.entity.ArticleTag;
import com.atlasmind.mapper.ArticleMapper;
import com.atlasmind.mapper.ArticleTagMapper;
import com.atlasmind.service.ArticleSearchService;
import com.atlasmind.service.ArticleService;
import com.atlasmind.service.TagService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 文章服务实现。
 * <p>
 * 重点：
 * <ul>
 *   <li>{@code getPublishedList} 置空 content 字段减少传输量；先按置顶降序再按时间降序</li>
 *   <li>{@code getDetail} 自增阅读量后更新数据库</li>
 *   <li>{@code getNav} 按时间查找上一篇/下一篇已发布文章</li>
 *   <li>{@code create/update} 通过 {@code ArticleTagMapper} 维护文章-标签关联，使用
 *       {@code @Transactional} 保证原子性；更新时先删后插</li>
 * </ul>
 */
@Service
public class ArticleServiceImpl implements ArticleService {

    private final ArticleMapper articleMapper;
    private final ArticleTagMapper articleTagMapper;
    private final TagService tagService;
    private final ArticleSearchService articleSearchService;

    public ArticleServiceImpl(ArticleMapper articleMapper,
                              ArticleTagMapper articleTagMapper,
                              TagService tagService,
                              @Autowired(required = false) ArticleSearchService articleSearchService) {
        this.articleMapper = articleMapper;
        this.articleTagMapper = articleTagMapper;
        this.tagService = tagService;
        this.articleSearchService = articleSearchService;
    }

    @Override
    public Page<Article> getPublishedList(int page, int size, Long categoryId, String keyword) {
        LambdaQueryWrapper<Article> wrapper = new LambdaQueryWrapper<Article>()
                .eq(Article::getVisibility, "PUBLIC")
                .orderByDesc(Article::getIsTop)
                .orderByDesc(Article::getCreateTime);
        if (categoryId != null) wrapper.eq(Article::getCategoryId, categoryId);
        if (keyword != null && !keyword.isBlank()) {
            wrapper.and(w -> w.like(Article::getTitle, keyword).or().like(Article::getSummary, keyword).or().like(Article::getContent, keyword));
        }
        Page<Article> result = articleMapper.selectPage(new Page<>(page, size), wrapper);
        result.getRecords().forEach(a -> {
            a.setContent(null);
            a.setTags(tagService.getByArticleId(a.getId()));
        });
        return result;
    }

    @Override
    public Article getDetail(Long id) {
        Article article = articleMapper.selectById(id);
        if (article == null || !"PUBLIC".equals(article.getVisibility())) {
            throw new IllegalArgumentException("文章不存在");
        }
        article.setViewCount(article.getViewCount() + 1);
        articleMapper.updateById(article);
        article.setTags(tagService.getByArticleId(id));
        return article;
    }

    @Override
    public Map<String, Object> getNav(Long id) {
        Article current = articleMapper.selectById(id);
        if (current == null) return Map.of();

        // prev: older article (largest create_time < current, status=1)
        var prevList = articleMapper.selectList(new LambdaQueryWrapper<Article>()
                .eq(Article::getVisibility, "PUBLIC")
                .lt(Article::getCreateTime, current.getCreateTime())
                .orderByDesc(Article::getCreateTime)
                .last("limit 1"));
        Map<String, Object> prev = null;
        if (!prevList.isEmpty()) {
            var a = prevList.get(0);
            prev = Map.of("id", a.getId(), "title", a.getTitle());
        }

        // next: newer article (smallest create_time > current, status=1)
        var nextList = articleMapper.selectList(new LambdaQueryWrapper<Article>()
                .eq(Article::getVisibility, "PUBLIC")
                .gt(Article::getCreateTime, current.getCreateTime())
                .orderByAsc(Article::getCreateTime)
                .last("limit 1"));
        Map<String, Object> next = null;
        if (!nextList.isEmpty()) {
            var a = nextList.get(0);
            next = Map.of("id", a.getId(), "title", a.getTitle());
        }

        return Map.of("prev", prev != null ? prev : Map.of(), "next", next != null ? next : Map.of());
    }

    @Override
    public Article getById(Long id) {
        return articleMapper.selectById(id);
    }

    @Override
    public Page<Article> getAdminList(int page, int size, Integer status, String visibility) {
        LambdaQueryWrapper<Article> wrapper = new LambdaQueryWrapper<Article>()
                .orderByDesc(Article::getCreateTime);
        if (status != null) wrapper.eq(Article::getStatus, status);
        if (visibility != null && !visibility.isBlank()) wrapper.eq(Article::getVisibility, visibility);
        return articleMapper.selectPage(new Page<>(page, size), wrapper);
    }

    @Override
    @Transactional
    public Article create(ArticleDto dto) {
        Article article = new Article();
        article.setTitle(dto.getTitle());
        article.setContent(dto.getContent());
        article.setSummary(dto.getSummary());
        article.setCover(dto.getCover());
        article.setCategoryId(dto.getCategoryId());
        article.setIsTop(dto.getIsTop() != null ? dto.getIsTop() : 0);
        article.setStatus(dto.getStatus() != null ? dto.getStatus() : 0);
        article.setVisibility(dto.getVisibility() != null ? dto.getVisibility() : "PUBLIC");
        article.setViewCount(0);
        LocalDateTime now = LocalDateTime.now();
        article.setCreateTime(now);
        article.setUpdateTime(now);
        articleMapper.insert(article);

        if (dto.getTagIds() != null) {
            for (Long tagId : dto.getTagIds()) {
                ArticleTag at = new ArticleTag();
                at.setArticleId(article.getId());
                at.setTagId(tagId);
                articleTagMapper.insert(at);
            }
        }
        return article;
    }

    @Override
    @Transactional
    public Article update(Long id, ArticleDto dto) {
        Article article = articleMapper.selectById(id);
        if (article == null) throw new IllegalArgumentException("文章不存在");
        article.setTitle(dto.getTitle());
        article.setContent(dto.getContent());
        article.setSummary(dto.getSummary());
        article.setCover(dto.getCover());
        article.setCategoryId(dto.getCategoryId());
        if (dto.getIsTop() != null) article.setIsTop(dto.getIsTop());
        if (dto.getStatus() != null) article.setStatus(dto.getStatus());
        if (dto.getVisibility() != null) article.setVisibility(dto.getVisibility());
        article.setUpdateTime(LocalDateTime.now());
        articleMapper.updateById(article);

        articleTagMapper.delete(new LambdaQueryWrapper<ArticleTag>().eq(ArticleTag::getArticleId, id));
        if (dto.getTagIds() != null) {
            for (Long tagId : dto.getTagIds()) {
                ArticleTag at = new ArticleTag();
                at.setArticleId(id);
                at.setTagId(tagId);
                articleTagMapper.insert(at);
            }
        }
        return article;
    }

    @Override
    public void delete(Long id) {
        articleTagMapper.delete(new LambdaQueryWrapper<ArticleTag>().eq(ArticleTag::getArticleId, id));
        articleMapper.deleteById(id);
    }

    @Override
    public Page<Article> search(String keyword, int page, int size) {
        // ES 可用时委托给 ES 搜索，否则回退 MySQL LIKE
        if (articleSearchService != null) {
            try {
                return articleSearchService.search(keyword, page, size);
            } catch (Exception e) {
                // ES 异常时静默回退 MySQL
            }
        }
        // MySQL LIKE 回退
        LambdaQueryWrapper<Article> wrapper = new LambdaQueryWrapper<Article>()
                .eq(Article::getVisibility, "PUBLIC")
                .and(w -> w.like(Article::getTitle, keyword)
                        .or().like(Article::getSummary, keyword)
                        .or().like(Article::getContent, keyword))
                .orderByDesc(Article::getCreateTime);
        Page<Article> result = articleMapper.selectPage(new Page<>(page, size), wrapper);
        result.getRecords().forEach(a -> {
            a.setContent(null);
            a.setTags(tagService.getByArticleId(a.getId()));
        });
        return result;
    }

    @Override
    public List<Map<String, Object>> getArchive() {
        List<Map<String, Object>> groups = articleMapper.getArchiveGroups();
        for (Map<String, Object> group : groups) {
            String yearMonth = (String) group.get("yearMonth");
            List<Article> articles = articleMapper.getArticlesByYearMonth(yearMonth);
            // 去掉 content 减少传输量
            articles.forEach(a -> {
                a.setContent(null);
                a.setTags(tagService.getByArticleId(a.getId()));
            });
            group.put("articles", articles);
        }
        return groups;
    }
}
