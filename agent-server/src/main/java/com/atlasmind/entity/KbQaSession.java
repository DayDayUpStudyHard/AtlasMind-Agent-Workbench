package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户端 AI 问答会话。
 */
@Data
@TableName("kb_qa_session")
public class KbQaSession {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String source;
    private String scope;
    private String ownerToken;
    private Long spaceId;
    private Long documentId;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
