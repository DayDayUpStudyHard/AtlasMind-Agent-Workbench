package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 说说实体，映射 {@code t_moment} 表。
 * <p>
 * 轻量级短文，有内容 + 可选配图，区别于长文章。
 */
@Data
@TableName("t_moment")
public class Moment {
    @TableId(type = IdType.AUTO)
    private Long id;
    @NotBlank(message = "说说内容不能为空")
    private String content;
    private String image;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
