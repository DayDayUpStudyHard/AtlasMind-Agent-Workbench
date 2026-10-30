package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 审批流程轮次，映射 {@code contract_flow} 表（phase-2-design §1.1）。
 *
 * <p>同一案件下每轮一行；撤回批准后开新轮，{@code parentFlowId} 指回上一轮。
 * 审批结论绑定 {@code (id, versionId)}，不在同一轮内改写版本。
 */
@Data
@TableName("contract_flow")
public class ContractFlow {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long caseId;
    private Integer roundNo;
    /** RUNNING / COMPLETED / CANCELLED */
    private String state;
    private Long versionId;
    private String startNode;
    private Long parentFlowId;
    private String baselineJson;
    private String baselineHash;
    private Long agentRunId;
    private Long startedBy;
    private LocalDateTime startedAt;
    private LocalDateTime endedAt;
    private String endReason;
}
