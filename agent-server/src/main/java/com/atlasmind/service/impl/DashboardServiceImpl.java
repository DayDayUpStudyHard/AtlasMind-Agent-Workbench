package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.entity.Article;
import com.atlasmind.entity.Comment;
import com.atlasmind.entity.KbDocument;
import com.atlasmind.entity.KbIngestJob;
import com.atlasmind.entity.Moment;
import com.atlasmind.mapper.ArticleMapper;
import com.atlasmind.mapper.CategoryMapper;
import com.atlasmind.mapper.CommentMapper;
import com.atlasmind.mapper.KbDocumentMapper;
import com.atlasmind.mapper.KbIngestJobMapper;
import com.atlasmind.mapper.MomentMapper;
import com.atlasmind.service.DashboardService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 统一计算管理端概览数据，避免前端并行拼装多个统计接口。
 */
@Service
@RequiredArgsConstructor
public class DashboardServiceImpl implements DashboardService {

    private final ArticleMapper articleMapper;
    private final CategoryMapper categoryMapper;
    private final CommentMapper commentMapper;
    private final MomentMapper momentMapper;
    private final KbDocumentMapper documentMapper;
    private final KbIngestJobMapper jobMapper;

    @Override
    public Map<String, Object> overview() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("articleCount", articleMapper.selectCount(null));
        result.put("categoryCount", categoryMapper.selectCount(null));
        result.put("commentCount", commentMapper.selectCount(null));
        result.put("momentCount", momentMapper.selectCount(null));
        result.put("knowledgeDocumentCount", documentMapper.selectCount(
                new LambdaQueryWrapper<KbDocument>().eq(KbDocument::getDeleted, 0)
        ));
        result.put("failedJobCount", jobMapper.selectCount(
                new LambdaQueryWrapper<KbIngestJob>().eq(KbIngestJob::getStatus, "FAILED")
        ));

        Page<Article> articles = articleMapper.selectPage(
                new Page<>(1, 5),
                new LambdaQueryWrapper<Article>().orderByDesc(Article::getCreateTime)
        );
        Page<Comment> comments = commentMapper.selectPage(
                new Page<>(1, 5),
                new LambdaQueryWrapper<Comment>().orderByDesc(Comment::getCreateTime)
        );
        result.put("recentArticles", articles.getRecords());
        result.put("recentComments", comments.getRecords());

        Page<Moment> moments = momentMapper.selectPage(
                new Page<>(1, 3),
                new LambdaQueryWrapper<Moment>().orderByDesc(Moment::getCreateTime)
        );
        result.put("recentMoments", moments.getRecords());
        return result;
    }
}
