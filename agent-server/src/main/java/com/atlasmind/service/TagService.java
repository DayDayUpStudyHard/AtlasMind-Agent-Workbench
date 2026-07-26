package com.atlasmind.service;

import com.atlasmind.entity.Tag;
import java.util.List;

/**
 * 标签服务接口。
 * <p>
 * {@code getByArticleId} 通过 {@code t_article_tag} 中间表查询某篇文章的标签列表。
 */
public interface TagService {
    List<Tag> list();
    Tag create(Tag tag);
    Tag update(Tag tag);
    void delete(Long id);
    List<Tag> getByArticleId(Long articleId);
}
