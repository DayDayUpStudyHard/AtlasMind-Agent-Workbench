package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 关于页实体，映射 {@code t_about} 表。
 * <p>
 * 单行表（id=1），存储关于页 Markdown 内容和时间线 JSON。
 */
@Data
@TableName("t_about")
public class About {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String content;
    private String timeline;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
}
