package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 知识库文档元数据。原始文件存储在文件系统，解析后的 chunk 存在 MySQL。
 */
@Data
@TableName("kb_document")
public class KbDocument {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long spaceId;
    private String title;
    private String fileName;
    private String fileType;
    private Long fileSize;
    private String filePath;
    private String status;
    private String parseMode;
    private Integer chunkCount;
    private String embeddingModel;
    private Integer embeddingDim;
    private String indexName;
    private LocalDateTime lastIndexTime;
    private String errorMessage;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
    private Integer deleted;

    @TableField(exist = false)
    private Long latestJobId;
    @TableField(exist = false)
    private String latestJobStatus;
    @TableField(exist = false)
    private Integer latestJobProgress;
    @TableField(exist = false)
    private String latestJobMessage;
    @TableField(exist = false)
    private String latestJobErrorMessage;
}
