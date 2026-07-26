package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 知识库空间，按主题组织个人学习、项目和面试资料。
 */
@Data
@TableName("kb_space")
public class KbSpace {
    @TableId(type = IdType.AUTO)
    private Long id;
    @NotBlank(message = "知识库名称不能为空")
    private String name;
    private String description;
    private String icon;
    private String color;
    private Integer sort;
    private Integer enabled;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
    @TableLogic
    private Integer deleted;
}
