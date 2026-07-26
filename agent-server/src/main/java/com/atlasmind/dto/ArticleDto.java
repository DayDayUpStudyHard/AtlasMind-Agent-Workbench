package com.atlasmind.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;
import java.util.List;

/**
 * 文章创建/编辑 DTO。
 * <p>
 * {@code tagIds} 为关联标签 ID 列表，后端在 {@code ArticleServiceImpl} 中维护
 * {@code t_article_tag} 中间表。
 */
@Data
public class ArticleDto {
    @NotBlank(message = "标题不能为空")
    private String title;
    @NotBlank(message = "内容不能为空")
    private String content;
    private String summary;
    private String cover;
    private Long categoryId;
    private List<Long> tagIds;
    private Integer isTop;
    private Integer status;
    /** 可见性：PUBLIC / RAG_ONLY / PRIVATE */
    private String visibility;
}
