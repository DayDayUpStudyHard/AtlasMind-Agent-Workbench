package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 知识库文档切片，是重建 ES 索引的事实源。
 */
@Data
@TableName("kb_document_chunk")
public class KbDocumentChunk {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long documentId;
    private Long spaceId;
    private Integer chunkIndex;
    private String sectionTitle;
    private Integer sourcePage;
    private String chunkText;
    private Integer charCount;
    private Integer tokenCount;
    private String embeddingStatus;
    private String indexStatus;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
    private Integer deleted;
}
