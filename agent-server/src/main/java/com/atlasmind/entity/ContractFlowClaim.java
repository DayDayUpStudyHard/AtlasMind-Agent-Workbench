package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 认领记录，映射 {@code contract_flow_claim} 表（phase-2-design §1.4）。
 * 追加式历史，节点当前持有者以 {@code contract_flow_node.assignee_id} 为准。
 */
@Data
@TableName("contract_flow_claim")
public class ContractFlowClaim {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long nodeId;
    private Long userId;
    private LocalDateTime claimedAt;
    private LocalDateTime releasedAt;
    /** MANUAL / TIMEOUT / FORCED / RETURNED / DONE */
    private String releaseReason;
}
