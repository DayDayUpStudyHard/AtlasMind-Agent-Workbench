package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.document.ArticleDocument;
import com.atlasmind.entity.Article;
import com.atlasmind.mapper.ArticleMapper;
import com.atlasmind.repository.ArticleSearchRepository;
import com.atlasmind.service.ArticleSearchService;
import com.atlasmind.service.EmbeddingService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * ES 文章搜索服务实现。
 * <p>
 * 通过 {@code atlasmind.search.type=elasticsearch} 条件启用。
 * 索引时生成 embedding 向量 → ES dense_vector，供 kNN 语义搜索。
 * 公共搜索只返回 visibility=PUBLIC 的文章。
 */
@Slf4j
@Service
@RequiredArgsConstructor
@ConditionalOnProperty(name = "atlasmind.search.type", havingValue = "elasticsearch", matchIfMissing = false)
public class ArticleSearchServiceImpl implements ArticleSearchService {

    private final ArticleSearchRepository searchRepository;
    private final ArticleMapper articleMapper;
    private final EmbeddingService embeddingService;

    @Override
    public Page<Article> search(String keyword, int page, int size) {
        Pageable pageable = PageRequest.of(page - 1, size);
        org.springframework.data.domain.Page<ArticleDocument> esPage =
                searchRepository.findByTitleContainingOrSummaryContainingOrContentContaining(
                        keyword, keyword, keyword, pageable);

        List<Article> articles = esPage.getContent().stream()
                .map(doc -> articleMapper.selectById(doc.getId()))
                .filter(a -> a != null && "PUBLIC".equals(a.getVisibility()))
                .toList();

        Page<Article> result = new Page<>(page, size);
        result.setRecords(articles);
        result.setTotal(esPage.getTotalElements());
        return result;
    }

    @Override
    public void index(Article article) {
        try {
            // 拼接文本生成语义向量
            String embedText = embeddingService.buildEmbeddingText(
                    article.getTitle(), article.getSummary(), article.getContent());
            float[] embedding = embeddingService.embed(embedText);

            ArticleDocument doc = ArticleDocument.builder()
                    .id(article.getId())
                    .title(article.getTitle())
                    .content(article.getContent())
                    .summary(article.getSummary())
                    .categoryId(article.getCategoryId())
                    .status(article.getStatus())
                    .visibility(article.getVisibility())
                    .embedding(embedding)  // dense_vector 语义向量
                    .createTime(article.getCreateTime())
                    .build();
            searchRepository.save(doc);
            log.debug("ES indexed article {} (embedding: {})",
                    article.getId(), embedding != null ? embedding.length + "d" : "none");
        } catch (Exception e) {
            log.warn("ES index failed for article {}: {}", article.getId(), e.getMessage());
        }
    }

    @Override
    public void delete(Long articleId) {
        try {
            searchRepository.deleteById(articleId);
            log.debug("ES deleted article: {}", articleId);
        } catch (Exception e) {
            log.warn("ES delete failed for article {}: {}", articleId, e.getMessage());
        }
    }
}
