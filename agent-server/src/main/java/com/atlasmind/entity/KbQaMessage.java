package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * AI 会话中的用户问题或助手回答。
 */
@Data
@TableName("kb_qa_message")
public class KbQaMessage {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long sessionId;
    private String role;
    private String content;
    private String model;
    private Long latencyMs;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
