package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.dto.CommentDto;
import com.atlasmind.entity.Comment;
import com.atlasmind.mapper.CommentMapper;
import com.atlasmind.service.CommentService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 评论服务实现。
 * <p>
 * 前台查询只返回 status=1 的评论；新评论默认 status=1（直接展示）。
 * 支持单层嵌套回复（楼中楼），回复不能再有子回复。
 * 后台可修改 status 实现审核/标记垃圾。
 */
@Service
@RequiredArgsConstructor
public class CommentServiceImpl implements CommentService {

    private final CommentMapper commentMapper;

    @Override
    public List<Comment> getByArticleId(Long articleId) {
        return commentMapper.selectList(
                new LambdaQueryWrapper<Comment>()
                        .eq(Comment::getArticleId, articleId)
                        .eq(Comment::getStatus, 1)
                        .orderByDesc(Comment::getCreateTime));
    }

    @Override
    public Comment create(Long articleId, CommentDto dto) {
        // 校验单层嵌套：回复的父评论必须是根评论（parentId 为 null）
        if (dto.getParentId() != null) {
            Comment parent = commentMapper.selectById(dto.getParentId());
            if (parent != null && parent.getParentId() != null) {
                throw new IllegalArgumentException("不支持多级嵌套回复");
            }
        }

        Comment comment = new Comment();
        comment.setArticleId(articleId);
        comment.setParentId(dto.getParentId());
        comment.setReplyTo(dto.getReplyTo());
        comment.setAuthor(dto.getAuthor());
        comment.setEmail(dto.getEmail());
        comment.setContent(dto.getContent());
        comment.setStatus(1);
        comment.setCreateTime(LocalDateTime.now());
        commentMapper.insert(comment);
        return comment;
    }

    @Override
    public Page<Comment> getAdminList(int page, int size, Integer status, Integer type) {
        LambdaQueryWrapper<Comment> wrapper = new LambdaQueryWrapper<Comment>()
                .orderByDesc(Comment::getCreateTime);
        if (status != null) wrapper.eq(Comment::getStatus, status);
        if (type != null) {
            if (type == 0) wrapper.isNull(Comment::getArticleId);
            else wrapper.isNotNull(Comment::getArticleId);
        }
        return commentMapper.selectPage(new Page<>(page, size), wrapper);
    }

    @Override
    public void updateStatus(Long id, Integer status) {
        Comment comment = commentMapper.selectById(id);
        if (comment == null) throw new IllegalArgumentException("留言不存在");
        comment.setStatus(status);
        commentMapper.updateById(comment);
    }

    @Override
    public void delete(Long id) {
        commentMapper.deleteById(id);
    }

    @Override
    public Page<Comment> getGuestbookList(int page, int size) {
        return commentMapper.selectPage(new Page<>(page, size),
                new LambdaQueryWrapper<Comment>()
                        .isNull(Comment::getArticleId)
                        .eq(Comment::getStatus, 1)
                        .orderByDesc(Comment::getCreateTime));
    }

    @Override
    public Comment createGuestbook(CommentDto dto) {
        Comment comment = new Comment();
        comment.setArticleId(null);
        comment.setAuthor(dto.getAuthor());
        comment.setEmail(dto.getEmail());
        comment.setContent(dto.getContent());
        comment.setStatus(1);
        comment.setCreateTime(LocalDateTime.now());
        commentMapper.insert(comment);
        return comment;
    }
}
