package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 签署件核对结果，映射 {@code contract_sign_check} 表（phase-2-design §1.6）。
 * 规则结果与 agent 提示分开存储；法务终裁写入 {@code decision}。
 */
@Data
@TableName("contract_sign_check")
public class ContractSignCheck {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long flowId;
    private Long versionId;
    private Long signedDocId;
    private String ruleResultJson;
    private String agentResultJson;
    /** MATCH / MISMATCH / UNKNOWN */
    private String verdict;
    private Long decidedBy;
    /** APPROVE / RERUN / ABANDON */
    private String decision;
    private LocalDateTime decidedAt;
}
