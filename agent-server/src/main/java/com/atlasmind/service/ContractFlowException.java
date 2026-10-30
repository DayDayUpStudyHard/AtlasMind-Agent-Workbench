package com.atlasmind.service;

/**
 * 流程动作被拒绝时抛出，携带稳定的原因码供前端置灰/提示。
 *
 * <p>原因码（design §2.4、§2.10、§2.11、§5）：
 * <ul>
 *   <li>{@code ALREADY_CLAIMED} 409 — 节点已被他人认领</li>
 *   <li>{@code NOT_CANDIDATE} 403 — 不在候选组</li>
 *   <li>{@code NOT_HOLDER} 403 — 不是当前持有者</li>
 *   <li>{@code WITHDRAW_PENDING_EXISTS} 409 — 已有未决撤回</li>
 *   <li>{@code SELF_APPROVE_FORBIDDEN} 403 — 申请人不能自批，需管理员</li>
 *   <li>{@code CANCEL_NOT_ALLOWED} 409 — 不满足取消条件</li>
 *   <li>{@code NO_APPROVER} 409 — 候选组为空，需管理员配置</li>
 *   <li>{@code CONFIRMATION_REQUIRED} 409 — 要素/日程尚未确认</li>
 *   <li>{@code INVALID_STATE}/{@code INVALID_TARGET} 409 — 状态或目标节点非法</li>
 * </ul>
 */
public class ContractFlowException extends RuntimeException {

    private final String reason;
    private final int status;

    public ContractFlowException(String reason, int status, String message) {
        super(message);
        this.reason = reason;
        this.status = status;
    }

    public String getReason() {
        return reason;
    }

    public int getStatus() {
        return status;
    }
}
