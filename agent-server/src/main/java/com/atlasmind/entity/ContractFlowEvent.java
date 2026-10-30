package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 只增不改的流程事件，映射 {@code contract_flow_event} 表（phase-2-design §1.3）。
 *
 * <p>{@code refId} 关联 agent_run_id / withdraw_id / sign_check_id；
 * {@code uk_event(flow_id, node_id, event_type, ref_id)} 用于重试去重。
 */
@Data
@TableName("contract_flow_event")
public class ContractFlowEvent {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long flowId;
    private Long nodeId;
    private String eventType;
    private Long actorId;
    /** USER / AGENT / SYSTEM */
    private String actorType;
    private String fromNode;
    private String toNode;
    private String payloadJson;
    private Long refId;
    private LocalDateTime createdAt;
}
