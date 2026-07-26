package com.atlasmind.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.entity.Article;

/**
 * Elasticsearch 文章搜索服务。
 * <p>
 * 负责 ES 索引的增删改查，与 {@link ArticleService} 配合使用。
 */
public interface ArticleSearchService {

    /**
     * 全文搜索已发布文章。
     */
    Page<Article> search(String keyword, int page, int size);

    /**
     * 索引文章（创建或更新时调用）。
     */
    void index(Article article);

    /**
     * 从 ES 索引中删除文章。
     */
    void delete(Long articleId);
}
