package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 额度流水实体，映射 {@code quota_transaction} 表。
 */
@Data
@TableName("quota_transaction")
public class QuotaTransaction {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private Integer amount;
    private String type;        // ALLOCATE | RESERVE | CONFIRM | REFUND | ADMIN_ADJUST
    private Integer balanceAfter;
    private Long operatorId;
    private Long runId;
    private String remark;
    private String idempotencyKey;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
}
