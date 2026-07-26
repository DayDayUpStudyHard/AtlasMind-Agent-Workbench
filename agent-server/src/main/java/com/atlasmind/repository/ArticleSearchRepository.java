package com.atlasmind.repository;

import com.atlasmind.document.ArticleDocument;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.elasticsearch.repository.ElasticsearchRepository;

/**
 * 文章 ES 搜索 Repository。
 * <p>
 * 继承 {@link ElasticsearchRepository} 获得基础 CRUD 能力，
 * 通过方法命名约定自动生成查询。
 */
public interface ArticleSearchRepository extends ElasticsearchRepository<ArticleDocument, Long> {

    /**
     * 多字段搜索：标题、摘要、内容。
     */
    Page<ArticleDocument> findByTitleContainingOrSummaryContainingOrContentContaining(
            String title, String summary, String content, Pageable pageable);
}
