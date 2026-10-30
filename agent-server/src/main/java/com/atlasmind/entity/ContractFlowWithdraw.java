package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 撤回申请，映射 {@code contract_flow_withdraw} 表（phase-2-design §1.5）。
 *
 * <p>{@code pendingFlag} 是数据库生成列（PENDING→1，其余→NULL），
 * 配合 {@code uk_flow_pending} 从数据库层挡住同一流程的第二个未决撤回。
 */
@Data
@TableName("contract_flow_withdraw")
public class ContractFlowWithdraw {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long flowId;
    private Long requesterId;
    private String targetNode;
    private String reason;
    /** PENDING / APPROVED / REJECTED / EXPIRED */
    private String state;
    @TableField(insertStrategy = FieldStrategy.NEVER, updateStrategy = FieldStrategy.NEVER)
    private Integer pendingFlag;
    private Long decidedBy;
    private LocalDateTime decidedAt;
    private LocalDateTime createdAt;
}
