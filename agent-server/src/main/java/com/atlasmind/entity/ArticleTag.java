package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

/**
 * 文章-标签关联表实体，映射 {@code t_article_tag}。
 * <p>
 * 通过 MyBatis-Plus {@code BaseMapper} 直接操作此表，无需单独 Mapper 的 XML。
 */
@Data
@TableName("t_article_tag")
public class ArticleTag {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long articleId;
    private Long tagId;
}
