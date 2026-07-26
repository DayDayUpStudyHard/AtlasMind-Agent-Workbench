package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 知识库文档异步导入任务。
 */
@Data
@TableName("kb_ingest_job")
public class KbIngestJob {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long documentId;
    private String jobType;
    private String status;
    private Integer progress;
    private String message;
    private String errorMessage;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
}
