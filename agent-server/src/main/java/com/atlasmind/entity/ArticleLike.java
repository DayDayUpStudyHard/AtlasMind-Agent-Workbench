package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 文章点赞实体，映射 {@code t_article_like} 表。
 * <p>
 * 基于 IP 去重，游客无需登录即可点赞。Redis Set 做高速去重，
 * MySQL 做持久化存储。
 */
@Data
@TableName("t_article_like")
public class ArticleLike {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long articleId;
    private String userIp;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
