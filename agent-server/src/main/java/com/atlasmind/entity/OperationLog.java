package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 操作日志实体 — 记录后台管理操作的审计信息。
 * <p>
 * 由 {@code OperationLogAspect} 通过 {@code @Async} 异步写入，不阻塞主请求。
 */
@Data
@TableName("t_operation_log")
public class OperationLog {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String username;
    private String ip;
    private String operation;
    private String type;
    private String methodName;
    private String args;
    private Long executionTime;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
