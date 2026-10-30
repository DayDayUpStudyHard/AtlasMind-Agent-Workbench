package com.atlasmind.service;

import java.util.List;

/** 二期流程枚举真源（docs/contract-workflow/phase-2-design.md §1、§2）。 */
public final class ContractFlowConstants {

    private ContractFlowConstants() {
    }

    // ── 节点 ──────────────────────────────────────────────────────
    public static final String NODE_UPLOADER = "UPLOADER";
    public static final String NODE_AGENT = "AGENT";
    public static final String NODE_DEPT_APPROVAL = "DEPT_APPROVAL";
    public static final String NODE_LEGAL_APPROVAL = "LEGAL_APPROVAL";
    public static final String NODE_SIGNING = "SIGNING";

    /** 线性节点链，顺序即 seq。 */
    public static final List<String> NODE_CHAIN = List.of(
            NODE_UPLOADER, NODE_AGENT, NODE_DEPT_APPROVAL, NODE_LEGAL_APPROVAL, NODE_SIGNING);

    /** 需要认领的人工节点；UPLOADER / SIGNING 由上传人直接操作。 */
    public static final List<String> CLAIMABLE_NODES = List.of(
            NODE_DEPT_APPROVAL, NODE_LEGAL_APPROVAL);

    // ── 节点状态 ──────────────────────────────────────────────────
    public static final String NODE_PENDING = "PENDING";
    public static final String NODE_CLAIMED = "CLAIMED";
    public static final String NODE_DONE = "DONE";
    public static final String NODE_BLOCKED = "BLOCKED";
    public static final String NODE_VOID = "VOID";
    public static final List<String> ACTIVE_NODE_STATES = List.of(NODE_PENDING, NODE_CLAIMED, NODE_BLOCKED);

    // ── 流程状态 ──────────────────────────────────────────────────
    public static final String FLOW_RUNNING = "RUNNING";
    public static final String FLOW_COMPLETED = "COMPLETED";
    public static final String FLOW_CANCELLED = "CANCELLED";
    public static final String END_WITHDRAWN = "WITHDRAWN";
    public static final String END_CANCELLED = "CANCELLED";
    public static final String END_ABANDONED = "ABANDONED";

    // ── 撤回状态 ──────────────────────────────────────────────────
    public static final String WITHDRAW_PENDING = "PENDING";
    public static final String WITHDRAW_APPROVED = "APPROVED";
    public static final String WITHDRAW_REJECTED = "REJECTED";
    public static final String WITHDRAW_EXPIRED = "EXPIRED";

    // ── 事件类型（design §1.3） ───────────────────────────────────
    public static final String EV_FLOW_START = "FLOW_START";
    public static final String EV_CANCEL = "CANCEL";
    public static final String EV_COMPLETE = "COMPLETE";
    public static final String EV_ABANDON = "ABANDON";
    public static final String EV_CLAIM = "CLAIM";
    public static final String EV_RELEASE = "RELEASE";
    public static final String EV_ENTER = "ENTER";
    public static final String EV_EDIT = "EDIT";
    public static final String EV_UPLOAD = "UPLOAD";
    public static final String EV_CONFIRM_ELEMENTS = "CONFIRM_ELEMENTS";
    public static final String EV_CONFIRM_TIMELINE = "CONFIRM_TIMELINE";
    public static final String EV_VERSION_SWITCH = "VERSION_SWITCH";
    public static final String EV_AGENT_RUN = "AGENT_RUN";
    public static final String EV_AGENT_FAIL = "AGENT_FAIL";
    public static final String EV_AGENT_RERUN = "AGENT_RERUN";
    public static final String EV_APPROVE = "APPROVE";
    public static final String EV_RETURN = "RETURN";
    public static final String EV_WITHDRAW_REQUEST = "WITHDRAW_REQUEST";
    public static final String EV_WITHDRAW_APPROVE = "WITHDRAW_APPROVE";
    public static final String EV_WITHDRAW_REJECT = "WITHDRAW_REJECT";
    public static final String EV_WITHDRAW_EXPIRE = "WITHDRAW_EXPIRE";
    public static final String EV_SIGN_UPLOAD = "SIGN_UPLOAD";
    public static final String EV_SIGN_CHECK = "SIGN_CHECK";
    public static final String EV_SIGN_DECISION = "SIGN_DECISION";

    // ── 角色 ──────────────────────────────────────────────────────
    public static final String ROLE_LEGAL = "LEGAL";

    // ── 候选组前缀 ────────────────────────────────────────────────
    public static final String GROUP_OWNER = "OWNER";
    public static final String GROUP_DEPT_PREFIX = "DEPT:";
    public static final String GROUP_LEGAL = "LEGAL";

    /** 待认领超时（小时）：取消判定与认领过期阈值。 */
    public static final int CANCEL_AFTER_HOURS = 6;
    /** 认领后自动放回阈值（小时，决策 #7）。 */
    public static final int CLAIM_EXPIRE_HOURS = 24;
}
