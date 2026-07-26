package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 后台消息中心通知，用于异步导入成功/失败提醒。
 */
@Data
@TableName("kb_notification")
public class KbNotification {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String type;
    private String title;
    private String content;
    private String relatedType;
    private Long relatedId;
    private Integer readStatus;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
