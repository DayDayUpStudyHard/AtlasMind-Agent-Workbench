package com.atlasmind.service.impl;

import com.atlasmind.dto.CommentDto;
import com.atlasmind.entity.Comment;
import com.atlasmind.mapper.CommentMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * CommentServiceImpl 单元测试 — 验证文章评论与留言板功能。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("评论服务单元测试")
class CommentServiceImplTest {

    @Mock
    private CommentMapper commentMapper;

    @InjectMocks
    private CommentServiceImpl commentService;

    @BeforeEach
    void setUp() {
        // mocks only, no shared state needed
    }

    @Test
    @DisplayName("文章评论 — 创建时默认 status=1")
    void createArticleComment() {
        CommentDto dto = new CommentDto();
        dto.setAuthor("张三");
        dto.setEmail("zhangsan@test.com");
        dto.setContent("好文章");

        Comment result = commentService.create(1L, dto);

        assertEquals("张三", result.getAuthor());
        assertEquals(1, result.getStatus());
        assertNotNull(result.getCreateTime());
        verify(commentMapper).insert(any(Comment.class));
    }

    @Test
    @DisplayName("留言板留言 — articleId 为 null")
    void createGuestbook() {
        CommentDto dto = new CommentDto();
        dto.setAuthor("访客");
        dto.setContent("留言内容");

        Comment result = commentService.createGuestbook(dto);

        assertNull(result.getArticleId());
        assertEquals(1, result.getStatus());
        verify(commentMapper).insert(any(Comment.class));
    }

    @Test
    @DisplayName("更新评论状态 — 审核通过")
    void updateStatus() {
        Comment comment = new Comment();
        comment.setId(1L);
        comment.setStatus(0);
        when(commentMapper.selectById(1L)).thenReturn(comment);

        commentService.updateStatus(1L, 1);

        assertEquals(1, comment.getStatus());
        verify(commentMapper).updateById(comment);
    }

    @Test
    @DisplayName("删除评论 — 按 ID 删除")
    void delete() {
        commentService.delete(1L);
        verify(commentMapper).deleteById(1L);
    }
}
