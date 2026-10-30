package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 流程节点实例，映射 {@code contract_flow_node} 表（phase-2-design §1.2）。
 *
 * <p>节点链线性无分支；任意时刻只有一个节点处于活跃态。
 * {@code VOID} 表示被打回后作废，事件保留、节点不删除。
 */
@Data
@TableName("contract_flow_node")
public class ContractFlowNode {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long flowId;
    /** UPLOADER / AGENT / DEPT_APPROVAL / LEGAL_APPROVAL / SIGNING */
    private String nodeKey;
    private Integer seq;
    /** PENDING / CLAIMED / DONE / BLOCKED / VOID */
    private String state;
    private Long assigneeId;
    private LocalDateTime claimedAt;
    private LocalDateTime claimExpiresAt;
    /** OWNER / DEPT:&lt;deptId&gt; / LEGAL */
    private String candidateGroup;
    private LocalDateTime enteredAt;
    private LocalDateTime doneAt;
    /** 字段而非内存状态，多实例安全（design §8 遗留项 2）。 */
    private Integer pendingRerun;
}
