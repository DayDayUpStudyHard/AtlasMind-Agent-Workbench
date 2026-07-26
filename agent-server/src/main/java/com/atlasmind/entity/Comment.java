package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 评论实体，映射 {@code t_comment} 表。
 * <p>
 * {@code status}: 0=待审 1=通过 2=垃圾，前台仅展示 status=1 的评论。
 * {@code parentId} 不为 NULL 表示该评论是对某条根评论的回复（仅支持单层嵌套）。
 */
@Data
@TableName("t_comment")
public class Comment {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long articleId;
    private Long parentId;
    private String replyTo;
    private String author;
    private String email;
    private String content;
    private Integer status;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
    /** 非数据库字段 — 该评论的回复列表，前端组装用 */
    @TableField(exist = false)
    private List<Comment> replies;
}
