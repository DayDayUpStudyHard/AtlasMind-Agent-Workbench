package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 用户合同分析额度实体，映射 {@code user_quota} 表。
 */
@Data
@TableName("user_quota")
public class UserQuota {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private Integer totalQuota;
    private Integer usedCount;
    private Integer reservedCount;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
