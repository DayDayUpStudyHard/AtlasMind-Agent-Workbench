package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.ArticleTag;
import com.atlasmind.entity.Tag;
import com.atlasmind.mapper.ArticleTagMapper;
import com.atlasmind.mapper.TagMapper;
import com.atlasmind.service.TagService;
import lombok.RequiredArgsConstructor;
import com.atlasmind.annotation.CacheShield;
import com.atlasmind.annotation.CacheShieldEvict;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 标签服务实现。
 * <p>
 * 删除标签时先删除 {@code t_article_tag} 关联数据，再删标签。
 * {@code getByArticleId} 通过关联表查出标签 ID 集合，再批量查询标签实体。
 */
@Service
@RequiredArgsConstructor
public class TagServiceImpl implements TagService {

    private final TagMapper tagMapper;
    private final ArticleTagMapper articleTagMapper;

    @CacheShield(value = "tags", key = "'all'", ttl = 30, ttlVariance = 10)
    @Override
    public List<Tag> list() {
        return tagMapper.selectList(null);
    }

    @CacheShieldEvict(value = "tags", allEntries = true)
    @Override
    public Tag create(Tag tag) {
        tag.setCreateTime(LocalDateTime.now());
        tagMapper.insert(tag);
        return tag;
    }

    @CacheShieldEvict(value = "tags", allEntries = true)
    @Override
    public Tag update(Tag tag) {
        tagMapper.updateById(tag);
        return tag;
    }

    @CacheShieldEvict(value = "tags", allEntries = true)
    @Override
    public void delete(Long id) {
        articleTagMapper.delete(new LambdaQueryWrapper<ArticleTag>().eq(ArticleTag::getTagId, id));
        tagMapper.deleteById(id);
    }

    @Override
    public List<Tag> getByArticleId(Long articleId) {
        List<Long> tagIds = articleTagMapper.selectList(
                new LambdaQueryWrapper<ArticleTag>().eq(ArticleTag::getArticleId, articleId))
                .stream().map(ArticleTag::getTagId).collect(Collectors.toList());
        if (tagIds.isEmpty()) return List.of();
        return tagMapper.selectBatchIds(tagIds);
    }
}
