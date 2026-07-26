package com.atlasmind.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 评论/留言 DTO。
 */
@Data
public class CommentDto {
    @NotBlank(message = "昵称不能为空")
    private String author;
    @jakarta.validation.constraints.Email(message = "邮箱格式不正确")
    private String email;
    @NotBlank(message = "内容不能为空")
    private String content;
    private Long parentId;
    private String replyTo;
}
