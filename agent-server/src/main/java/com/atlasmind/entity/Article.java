package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 文章实体，映射 {@code t_article} 表。
 * <p>
 * 重点：
 * <ul>
 *   <li>{@code tags} 为 {@code @TableField(exist=false)} 非数据库字段，通过关联表查询后注入</li>
 *   <li>{@code deleted} 使用 {@code @TableLogic} 逻辑删除，删除操作变为 UPDATE</li>
 *   <li>{@code createTime/updateTime} 由 MyBatis-Plus 自动填充</li>
 * </ul>
 */
@Data
@TableName("t_article")
public class Article {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String title;
    private String content;
    private String summary;
    private Long categoryId;
    private String cover;
    private Integer isTop;
    private Integer status;
    /** 可见性：PUBLIC（展示+RAG）、RAG_ONLY（仅RAG）、PRIVATE（私有） */
    private String visibility;
    private Integer viewCount;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
    @TableLogic
    private Integer deleted;
    @TableField(exist = false)
    private List<Tag> tags;
}
