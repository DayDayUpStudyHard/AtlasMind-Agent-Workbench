package com.atlasmind.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.atlasmind.service.ContractFlowConstants.*;

/**
 * 二期审批流程核心服务（写侧）。
 *
 * <p>实现 docs/contract-workflow/phase-2-design.md 的流程动作：
 * 开启轮次、提交、认领/放回、通过、打回、撤回、取消、agent 推进。
 *
 * <p><b>事务契约（§2.11）</b>：每个动作的状态变更与事件写入在同一个事务内，
 * 抛异常即整体回滚；不捕获后吞掉任何异常。
 * <b>并发契约</b>：认领使用条件 UPDATE 乐观锁；审批类动作先 {@code FOR UPDATE} 取行锁。
 * <b>事件幂等</b>：{@code uk_event(flow_id,node_id,event_type,ref_id)} 挡住重试重复写入。
 */
@Service
@RequiredArgsConstructor
public class ContractFlowService {

    private static final ObjectMapper JSON = new ObjectMapper();
    private static final DateTimeFormatter TS = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss");

    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;

    // ══════════════════════════════════════════════════════════════
    // 开启 / 提交
    // ══════════════════════════════════════════════════════════════

    /**
     * 开启一轮流程。
     *
     * <p>同一案件已有 RUNNING 轮次 → {@code INVALID_STATE}。
     * 同一版本已被<b>用户取消</b>的轮次占用 → {@code VERSION_CANCELLED}（须换版本）。
     * 因撤回而关闭的轮次不算冲突（design §2.10 #7）。
     */
    public Long startFlow(Long caseId, Long versionId, String baselineJson, Long userId) {
        return tx.execute(status -> {
            lockCase(caseId);
            Integer running = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM contract_flow WHERE case_id=? AND state=?",
                    Integer.class, caseId, FLOW_RUNNING);
            if (running != null && running > 0) {
                throw conflict("INVALID_STATE", "该案件已有进行中的流程");
            }
            Integer cancelledSameVersion = jdbc.queryForObject("""
                    SELECT COUNT(*) FROM contract_flow
                    WHERE case_id=? AND version_id=? AND state='CANCELLED'
                      AND (end_reason IS NULL OR end_reason<>?)
                    """, Integer.class, caseId, versionId, END_WITHDRAWN);
            if (cancelledSameVersion != null && cancelledSameVersion > 0) {
                throw conflict("VERSION_CANCELLED", "该版本流程已取消，请换版本重新上传");
            }
            Integer nextRound = jdbc.queryForObject(
                    "SELECT COALESCE(MAX(round_no),0)+1 FROM contract_flow WHERE case_id=?",
                    Integer.class, caseId);
            Long flowId = createFlow(caseId, nextRound, versionId, NODE_UPLOADER, null,
                    baselineJson, userId);
            // §1.3 挂载规则：FLOW_START 挂 start_node
            addEvent(flowId, firstNodeId(flowId, NODE_UPLOADER), EV_FLOW_START, userId, "USER",
                    null, NODE_UPLOADER,
                    Map.of("roundNo", nextRound, "startNode", NODE_UPLOADER), null);
            addEvent(flowId, firstNodeId(flowId, NODE_UPLOADER), EV_ENTER, userId, "USER",
                    null, NODE_UPLOADER, null, null);
            return flowId;
        });
    }

    /**
     * 上传人提交：要求要素与日程均已确认，且两处候选组非空。
     * 成功后 UPLOADER → DONE，AGENT → PENDING。
     */
    public void submit(Long nodeId, Long userId) {
        tx.executeWithoutResult(status -> {
            Map<String, Object> node = lockNode(nodeId);
            Long flowId = asLong(node.get("flow_id"));
            Map<String, Object> flow = requireRunningFlow(flowId);
            if (!NODE_UPLOADER.equals(node.get("node_key"))) {
                throw conflict("INVALID_STATE", "当前不是上传人节点");
            }
            // 上传人节点由案件创建人/维护人持有，ADMIN 可兜底但必须留痕（决策 14）
            boolean fallback = requireUploader(caseIdOf(flowId), userId);
            requireConfirmations(flowId);
            Long deptId = jdbc.queryForObject(
                    "SELECT department_id FROM contract_case WHERE id=?", Long.class, caseIdOf(flowId));
            if (deptId == null || deptCandidates(deptId).isEmpty()) {
                throw conflict("NO_APPROVER", "该部门尚未配置审批人，请联系管理员");
            }
            if (legalCandidates().isEmpty()) {
                throw conflict("NO_APPROVER", "法务组尚未配置成员，请联系管理员");
            }
            if (fallback) {
                addEvent(flowId, nodeId, EV_ADMIN_OVERRIDE, userId, "USER", null, null,
                        Map.of("nodeKey", NODE_UPLOADER, "reason", "CANDIDATE_FALLBACK"), null);
            }
            markDone(node);
            Long agentNodeId = nodeId(flowId, NODE_AGENT);
            enterNode(agentNodeId, "SYSTEM");
            addEvent(flowId, agentNodeId, EV_ENTER, userId, "USER", NODE_UPLOADER, NODE_AGENT,
                    null, null);
        });
    }

    // ══════════════════════════════════════════════════════════════
    // 认领 / 放回
    // ══════════════════════════════════════════════════════════════

    /** 认领：条件 UPDATE 乐观锁，影响行数为 0 → 409 ALREADY_CLAIMED。 */
    public void claim(Long nodeId, Long userId) {
        doClaim(nodeId, userId, false);
    }

    /**
     * ADMIN 强制认领（design v0.4 §5）：绕过候选组，但必须留 {@code ADMIN_OVERRIDE}。
     * 除候选组校验外，其余并发与状态约束与普通认领完全一致。
     */
    public void forceClaim(Long nodeId, Long userId) {
        doClaim(nodeId, userId, true);
    }

    private void doClaim(Long nodeId, Long userId, boolean force) {
        tx.executeWithoutResult(status -> {
            Map<String, Object> node = jdbc.queryForMap(
                    "SELECT * FROM contract_flow_node WHERE id=?", nodeId);
            Long flowId = asLong(node.get("flow_id"));
            requireRunningFlow(flowId);
            String nodeKey = String.valueOf(node.get("node_key"));
            if (!CLAIMABLE_NODES.contains(nodeKey)) {
                throw conflict("INVALID_STATE", "该节点无需认领");
            }
            if (force) {
                if (!isAdmin(userId)) {
                    throw forbidden("NOT_ADMIN", "只有管理员可以强制认领");
                }
            } else if (!isCandidate(flowId, nodeKey, userId)) {
                throw forbidden("NOT_CANDIDATE", "你不在该节点的候选组");
            }
            Integer holding = jdbc.queryForObject("""
                    SELECT COUNT(*) FROM contract_flow_node
                    WHERE flow_id=? AND assignee_id=? AND state='CLAIMED' AND id<>?
                    """, Integer.class, flowId, userId, nodeId);
            if (holding != null && holding > 0) {
                throw conflict("INVALID_STATE", "你已持有本流程的其他节点");
            }
            LocalDateTime now = LocalDateTime.now();
            int updated = jdbc.update("""
                    UPDATE contract_flow_node
                    SET assignee_id=?, state=?, claimed_at=?, claim_expires_at=?
                    WHERE id=? AND state=? AND assignee_id IS NULL
                    """, userId, NODE_CLAIMED, now, now.plusHours(CLAIM_EXPIRE_HOURS), nodeId, NODE_PENDING);
            if (updated == 0) {
                throw conflict("ALREADY_CLAIMED", "该节点已被他人认领");
            }
            jdbc.update("""
                    INSERT INTO contract_flow_claim(node_id,user_id,claimed_at)
                    VALUES(?,?,?)
                    """, nodeId, userId, now);
            addEvent(flowId, nodeId, EV_CLAIM, userId, "USER", null, null,
                    Map.of("nodeKey", nodeKey), null);
            if (force) {
                // 单独一条事件，时间轴上必须看得见"管理员越过了候选组"
                addEvent(flowId, nodeId, EV_ADMIN_OVERRIDE, userId, "USER", null, null,
                        Map.of("nodeKey", nodeKey,
                                "candidateCount", candidates(flowId, nodeKey).size()), null);
            }
        });
    }

    /** 放回：MANUAL / TIMEOUT / FORCED；重新进入待认领并重置 6 小时时钟。 */
    public void release(Long nodeId, Long userId, String reason) {
        tx.executeWithoutResult(status -> {
            Map<String, Object> node = lockNode(nodeId);
            Long flowId = asLong(node.get("flow_id"));
            requireRunningFlow(flowId);
            Long holder = asLong(node.get("assignee_id"));
            if (holder == null) {
                throw conflict("INVALID_STATE", "该节点未被认领");
            }
            boolean forced = "FORCED".equals(reason);
            if (!forced && !holder.equals(userId) && !isAdmin(userId)) {
                throw forbidden("NOT_HOLDER", "只有持有者可以放回");
            }
            LocalDateTime now = LocalDateTime.now();
            jdbc.update("""
                    UPDATE contract_flow_node
                    SET assignee_id=NULL, state=?, claimed_at=NULL, claim_expires_at=NULL, entered_at=?
                    WHERE id=?
                    """, NODE_PENDING, now, nodeId);
            closeOpenClaim(nodeId, now, reason == null ? "MANUAL" : reason);
            addEvent(flowId, nodeId, EV_RELEASE, userId,
                    forced ? "SYSTEM" : "USER", null, null,
                    Map.of("reason", reason == null ? "MANUAL" : reason), null);
        });
    }

    // ══════════════════════════════════════════════════════════════
    // 通过 / 打回
    // ══════════════════════════════════════════════════════════════

    /** 通过：仅当前持有者可操作；节点 DONE 后推进链，未决撤回置 EXPIRED。 */
    public void approve(Long nodeId, Long userId, String comment) {
        tx.executeWithoutResult(status -> {
            Map<String, Object> node = lockNode(nodeId);
            Long flowId = asLong(node.get("flow_id"));
            requireRunningFlow(flowId);
            String nodeKey = String.valueOf(node.get("node_key"));
            if (!CLAIMABLE_NODES.contains(nodeKey)) {
                throw conflict("INVALID_STATE", "该节点不支持审批通过");
            }
            requireHolder(node, userId);
            if (!NODE_CLAIMED.equals(node.get("state"))) {
                throw conflict("INVALID_STATE", "节点尚未被认领");
            }
            expirePendingWithdraw(flowId, "APPROVED_BY_HOLDER");
            markDone(node);
            closeOpenClaim(nodeId, LocalDateTime.now(), "DONE");
            addEvent(flowId, nodeId, EV_APPROVE, userId, "USER", nodeKey, null,
                    comment == null || comment.isBlank() ? null : Map.of("comment", comment), null);
            advanceAfter(flowId, nodeKey, userId);
        });
    }

    /**
     * 打回：任意前序节点。当前节点及中间节点置 VOID，目标节点重新 PENDING。
     * 未决撤回置 EXPIRED（SUPERSEDED）。
     */
    public void returnTo(Long nodeId, Long userId, String toNode, String reason) {
        if (reason == null || reason.trim().isEmpty()) {
            throw conflict("INVALID_TARGET", "打回必须填写理由");
        }
        tx.executeWithoutResult(status -> {
            Map<String, Object> node = lockNode(nodeId);
            Long flowId = asLong(node.get("flow_id"));
            requireRunningFlow(flowId);
            String nodeKey = String.valueOf(node.get("node_key"));
            requireHolder(node, userId);
            int currentSeq = ((Number) node.get("seq")).intValue();
            Integer targetSeq = seqOf(toNode);
            if (targetSeq == null || targetSeq >= currentSeq) {
                throw conflict("INVALID_TARGET", "只能打回到当前节点之前的节点");
            }
            LocalDateTime now = LocalDateTime.now();
            jdbc.update("""
                    UPDATE contract_flow_node SET state=?, done_at=NULL
                    WHERE flow_id=? AND seq>=? AND seq<=? AND state<>?
                    """, NODE_VOID, flowId, targetSeq, currentSeq, NODE_VOID);
            jdbc.update("""
                    UPDATE contract_flow_node
                    SET state=?, assignee_id=NULL, claimed_at=NULL, claim_expires_at=?, entered_at=?, done_at=NULL
                    WHERE flow_id=? AND seq=?
                    """, NODE_PENDING, null, now, flowId, targetSeq);
            closeOpenClaim(nodeId, now, "RETURNED");
            expirePendingWithdraw(flowId, "SUPERSEDED");
            addEvent(flowId, nodeId, EV_RETURN, userId, "USER", nodeKey, toNode,
                    Map.of("reason", reason.trim()), null);
            Long targetNodeId = nodeId(flowId, toNode);
            addEvent(flowId, targetNodeId, EV_ENTER, userId, "USER", nodeKey, toNode, null, null);
        });
    }

    // ══════════════════════════════════════════════════════════════
    // 撤回
    // ══════════════════════════════════════════════════════════════

    /**
     * 申请撤回。同一流程只能有一个未决申请（数据库唯一索引兜底）。
     * 申请人可以是任意参与者；批准权在当前持有者，且不能自批。
     */
    public Long requestWithdraw(Long flowId, Long requesterId, String targetNode, String reason) {
        if (reason == null || reason.trim().isEmpty()) {
            throw conflict("INVALID_TARGET", "撤回必须填写理由");
        }
        if (seqOf(targetNode) == null) {
            throw conflict("INVALID_TARGET", "撤回目标节点非法");
        }
        return tx.execute(status -> {
            requireRunningFlow(flowId);
            Long id;
            try {
                jdbc.update("""
                        INSERT INTO contract_flow_withdraw(flow_id,requester_id,target_node,reason,state)
                        VALUES(?,?,?,?,?)
                        """, flowId, requesterId, targetNode, reason.trim(), WITHDRAW_PENDING);
                id = jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);
            } catch (DuplicateKeyException e) {
                // 唯一索引挡下第二个未决申请：这是预期的并发保护，转换为稳定原因码
                throw conflict("WITHDRAW_PENDING_EXISTS", "该流程已有未决的撤回申请");
            }
            // §1.3 挂载规则：WITHDRAW_* 挂当前活跃节点
            addEvent(flowId, anchorNodeId(flowId), EV_WITHDRAW_REQUEST, requesterId, "USER",
                    null, targetNode, Map.of("withdrawId", id, "reason", reason.trim()), id);
            return id;
        });
    }

    /**
     * 批准 / 驳回撤回。
     *
     * <p>批准：旧轮 CANCELLED(WITHDRAWN) → 新轮 round+1、parent_flow_id、start_node=目标节点，
     * 目标节点之前的节点直接 DONE（不重复劳动）。<b>不在同一轮回退</b>（design §2.6）。
     */
    public void decideWithdraw(Long withdrawId, Long userId, boolean approved, String comment) {
        tx.executeWithoutResult(status -> {
            Map<String, Object> w = jdbc.queryForMap(
                    "SELECT * FROM contract_flow_withdraw WHERE id=? FOR UPDATE", withdrawId);
            Long flowId = asLong(w.get("flow_id"));
            Map<String, Object> flow = requireRunningFlow(flowId);
            if (!WITHDRAW_PENDING.equals(w.get("state"))) {
                throw conflict("INVALID_STATE", "该撤回申请已处理");
            }
            Map<String, Object> currentNode = currentActiveNode(flowId);
            if (currentNode == null) {
                throw conflict("INVALID_STATE", "流程没有活跃节点");
            }
            Long holderId = asLong(currentNode.get("assignee_id"));
            boolean admin = isAdmin(userId);
            if (!admin && holderId != null && holderId.equals(asLong(w.get("requester_id")))) {
                throw forbidden("SELF_APPROVE_FORBIDDEN", "申请人不能批准自己的撤回，请转管理员");
            }
            if (!admin && (holderId == null || !holderId.equals(userId))) {
                throw forbidden("NOT_HOLDER", "只有当前持有者可以处理撤回");
            }
            LocalDateTime now = LocalDateTime.now();
            if (!approved) {
                jdbc.update("""
                        UPDATE contract_flow_withdraw
                        SET state=?, decided_by=?, decided_at=? WHERE id=?
                        """, WITHDRAW_REJECTED, userId, now, withdrawId);
                addEvent(flowId, asLong(currentNode.get("id")), EV_WITHDRAW_REJECT, userId, "USER",
                        null, null, Map.of("withdrawId", withdrawId,
                                "comment", comment == null ? "" : comment), withdrawId);
                return;
            }
            jdbc.update("""
                    UPDATE contract_flow_withdraw
                    SET state=?, decided_by=?, decided_at=? WHERE id=?
                    """, WITHDRAW_APPROVED, userId, now, withdrawId);
            jdbc.update("""
                    UPDATE contract_flow SET state=?, ended_at=?, end_reason=? WHERE id=?
                    """, FLOW_CANCELLED, now, END_WITHDRAWN, flowId);
            addEvent(flowId, asLong(currentNode.get("id")), EV_WITHDRAW_APPROVE, userId, "USER",
                    null, null, Map.of("withdrawId", withdrawId), withdrawId);

            Long caseId = asLong(flow.get("case_id"));
            String targetNode = String.valueOf(w.get("target_node"));
            Long versionId = latestVersionId(caseId);
            if (versionId == null) {
                versionId = asLong(flow.get("version_id"));
            }
            Integer nextRound = jdbc.queryForObject(
                    "SELECT COALESCE(MAX(round_no),0)+1 FROM contract_flow WHERE case_id=?",
                    Integer.class, caseId);
            Long newFlowId = createFlow(caseId, nextRound, versionId, targetNode, flowId,
                    String.valueOf(flow.get("baseline_json")), asLong(w.get("requester_id")));
            // §1.3 挂载规则：FLOW_START 挂 start_node（撤回重走时就是 target_node）
            addEvent(newFlowId, nodeId(newFlowId, targetNode), EV_FLOW_START,
                    asLong(w.get("requester_id")), "USER", null, targetNode,
                    Map.of("roundNo", nextRound, "startNode", targetNode,
                            "parentFlowId", flowId, "trigger", "WITHDRAW"), null);
            addEvent(newFlowId, nodeId(newFlowId, targetNode), EV_ENTER,
                    asLong(w.get("requester_id")), "USER", null, targetNode, null, null);
        });
    }

    // ══════════════════════════════════════════════════════════════
    // 取消
    // ══════════════════════════════════════════════════════════════

    /**
     * 取消本轮流程。仅两条路径可取消（design §2.4）：
     * 当前节点待认领满 6 小时，或 AGENT 节点 BLOCKED。取消不终止案件、不可重开。
     */
    public void cancel(Long flowId, Long userId, String reason) {
        tx.executeWithoutResult(status -> {
            requireRunningFlow(flowId);
            Map<String, Object> eligibility = cancelEligibility(flowId);
            if (!Boolean.TRUE.equals(eligibility.get("allowed"))) {
                throw conflict("CANCEL_NOT_ALLOWED", String.valueOf(eligibility.get("message")));
            }
            expirePendingWithdraw(flowId, "FLOW_CANCELLED");
            // 取消前先取挂载节点：取消只改 flow 状态，节点仍在活跃态
            Long anchor = anchorNodeId(flowId);
            jdbc.update("""
                    UPDATE contract_flow SET state=?, ended_at=?, end_reason=? WHERE id=?
                    """, FLOW_CANCELLED, LocalDateTime.now(), END_CANCELLED, flowId);
            addEvent(flowId, anchor, EV_CANCEL, userId, "USER", null, null,
                    Map.of("reason", reason == null ? "" : reason), null);
        });
    }

    /** 取消资格：返回 allowed / reasonCode / message / remainingMinutes。 */
    public Map<String, Object> cancelEligibility(Long flowId) {
        Map<String, Object> result = new LinkedHashMap<>();
        Map<String, Object> current = currentActiveNode(flowId);
        if (current == null) {
            result.put("allowed", false);
            result.put("reasonCode", "NO_ACTIVE_NODE");
            result.put("message", "当前没有可取消的活跃节点");
            return result;
        }
        String nodeKey = String.valueOf(current.get("node_key"));
        if (NODE_AGENT.equals(nodeKey) && NODE_BLOCKED.equals(current.get("state"))) {
            result.put("allowed", true);
            result.put("reasonCode", "AGENT_FAILED");
            return result;
        }
        if (NODE_PENDING.equals(current.get("state"))) {
            LocalDateTime entered = toLocalDateTime(current.get("entered_at"));
            LocalDateTime deadline = entered.plusHours(CANCEL_AFTER_HOURS);
            LocalDateTime now = LocalDateTime.now();
            if (!now.isBefore(deadline)) {
                result.put("allowed", true);
                result.put("reasonCode", "PENDING_TIMEOUT");
                return result;
            }
            long minutes = java.time.Duration.between(now, deadline).toMinutes();
            result.put("allowed", false);
            result.put("reasonCode", "PENDING_TOO_EARLY");
            result.put("remainingMinutes", minutes);
            result.put("message", "待认领未满 " + CANCEL_AFTER_HOURS + " 小时，还差 "
                    + (minutes / 60) + " 小时 " + (minutes % 60) + " 分");
            return result;
        }
        result.put("allowed", false);
        result.put("reasonCode", "HOLDER_PROCESSING");
        result.put("message", "当前有认领人正在处理，不能取消");
        return result;
    }

    // ══════════════════════════════════════════════════════════════
    // agent 推进（Java 轮询契约，design §2.9）
    // ══════════════════════════════════════════════════════════════

    /**
     * Python 状态回报。幂等：同一 {@code (node, agent_run_id)} 的成功/失败事件只写一次。
     *
     * <p>若运行期间收到过重跑请求（{@code pending_rerun=1}），成功后被合并为一次
     * AGENT_RERUN，节点保持 PENDING 等待下一轮。
     */
    public void onAgentFinished(Long flowId, Long agentRunId, Long userId, boolean succeeded, String detailJson) {
        tx.executeWithoutResult(status -> {
            Map<String, Object> flow = requireRunningFlow(flowId);
            Long nodeId = nodeId(flowId, NODE_AGENT);
            if (nodeId == null) {
                return;
            }
            Map<String, Object> node = lockNode(nodeId);
            if (NODE_DONE.equals(node.get("state")) || NODE_VOID.equals(node.get("state"))) {
                // 幂等：轮询/重试重复回报同一 agent 状态时不再推进链
                return;
            }
            boolean pendingRerun = ((Number) node.getOrDefault("pending_rerun", 0)).intValue() == 1;
            LocalDateTime now = LocalDateTime.now();
            jdbc.update("UPDATE contract_flow SET agent_run_id=? WHERE id=?", agentRunId, flowId);
            if (!succeeded) {
                jdbc.update("UPDATE contract_flow_node SET state=?, pending_rerun=0 WHERE id=?",
                        NODE_BLOCKED, nodeId);
                addEventRaw(flowId, nodeId, EV_AGENT_FAIL, userId, "AGENT", null, null,
                        detailJson, agentRunId);
                return;
            }
            addEventRaw(flowId, nodeId, EV_AGENT_RUN, userId, "AGENT", null, null,
                    detailJson, agentRunId);
            if (pendingRerun) {
                jdbc.update("UPDATE contract_flow_node SET state=?, pending_rerun=0, entered_at=? WHERE id=?",
                        NODE_PENDING, now, nodeId);
                addEvent(flowId, nodeId, EV_AGENT_RERUN, null, "SYSTEM", null, null,
                        Map.of("trigger", "MERGED_RERUN"), null);
                return;
            }
            jdbc.update("UPDATE contract_flow_node SET state=?, done_at=? WHERE id=?",
                    NODE_DONE, now, nodeId);
            // AGENT_RUN 已记录本次运行；推进链由 ENTER 事件表达，不伪造 APPROVE
            advanceAfter(flowId, NODE_AGENT, null);
        });
    }

    /** 合并重跑：agent 运行中再次触发时只置标志，不新开运行。 */
    public void requestAgentRerun(Long flowId, String trigger) {
        tx.executeWithoutResult(status -> {
            requireRunningFlow(flowId);
            Long nodeId = nodeId(flowId, NODE_AGENT);
            if (nodeId == null) {
                return;
            }
            jdbc.update("UPDATE contract_flow_node SET pending_rerun=1 WHERE id=? AND state<>?",
                    nodeId, NODE_DONE);
            addEvent(flowId, nodeId, EV_AGENT_RERUN, null, "SYSTEM", null, null,
                    Map.of("trigger", trigger == null ? "CONTENT_CHANGED" : trigger), null);
        });
    }

    // ══════════════════════════════════════════════════════════════
    // 查询
    // ══════════════════════════════════════════════════════════════

    /** 当前轮 + 当前节点 + 持有者 + 候选数 + 撤回 + 取消资格。 */
    public Map<String, Object> current(Long caseId) {
        List<Map<String, Object>> flows = jdbc.queryForList("""
                SELECT * FROM contract_flow WHERE case_id=? AND state=? ORDER BY round_no DESC LIMIT 1
                """, caseId, FLOW_RUNNING);
        if (flows.isEmpty()) {
            return null;
        }
        Map<String, Object> flow = flows.get(0);
        Long flowId = asLong(flow.get("id"));
        Map<String, Object> node = currentActiveNode(flowId);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("flowId", flowId);
        out.put("caseId", caseId);
        out.put("roundNo", flow.get("round_no"));
        out.put("state", flow.get("state"));
        out.put("versionId", flow.get("version_id"));
        out.put("startNode", flow.get("start_node"));
        out.put("parentFlowId", flow.get("parent_flow_id"));
        out.put("node", node == null ? null : nodeView(flowId, node));
        List<Map<String, Object>> pending = jdbc.queryForList(
                "SELECT * FROM contract_flow_withdraw WHERE flow_id=? AND state=?",
                flowId, WITHDRAW_PENDING);
        out.put("pendingWithdraw", pending.isEmpty() ? null : pending.get(0));
        out.put("cancelEligibility", cancelEligibility(flowId));
        return out;
    }

    // ══════════════════════════════════════════════════════════════
    // 内容类动作（§3.1 第 3 步：confirm-* / edit / version）
    // ══════════════════════════════════════════════════════════════

    /** 实质字段清单（§2.8）：变了才触发 agent 重跑。 */
    public static final List<String> SUBSTANTIVE_FIELDS = List.of(
            "amount", "currency", "partyA", "partyB", "startDate", "endDate",
            "paymentTerms", "breachClause", "liabilityCap");

    /** 上传人确认合同要素；重复确认在失效前幂等。 */
    public void confirmElements(Long caseId, Long userId) {
        confirmUploaderNode(caseId, userId, EV_CONFIRM_ELEMENTS);
    }

    /** 上传人确认履约日程；重复确认在失效前幂等。 */
    public void confirmTimeline(Long caseId, Long userId) {
        confirmUploaderNode(caseId, userId, EV_CONFIRM_TIMELINE);
    }

    private void confirmUploaderNode(Long caseId, Long userId, String eventType) {
        tx.executeWithoutResult(status -> {
            Map<String, Object> flow = requireRunningFlowOfCase(caseId);
            Long flowId = asLong(flow.get("id"));
            Map<String, Object> node = requireUploaderNode(flowId, "只有在上传人节点才能确认");
            boolean fallback = requireUploader(caseId, userId);
            // 幂等：失效水位之后已经确认过就不再追加事件，避免重复点击堆记录
            Integer existing = jdbc.queryForObject("""
                    SELECT COUNT(*) FROM contract_flow_event
                    WHERE flow_id=? AND event_type=? AND id>?
                    """, Integer.class, flowId, eventType, lastConfirmationInvalidationId(flowId));
            if (existing != null && existing > 0) {
                return;
            }
            Long anchor = asLong(node.get("id"));
            addEvent(flowId, anchor, eventType, userId, "USER", null, null, null, null);
            if (fallback) {
                addEvent(flowId, anchor, EV_ADMIN_OVERRIDE, userId, "USER", null, null,
                        Map.of("nodeKey", NODE_UPLOADER, "reason", "CANDIDATE_FALLBACK"), null);
            }
        });
    }

    /**
     * 修改实质字段（§2.7）。只允许在 UPLOADER / AGENT 节点发生；
     * 审批开始后必须走撤回流程。变更摘要与前后值写入 EDIT 事件。
     *
     * @return 是否有实质字段发生变化（决定是否触发 agent 重跑）
     */
    public boolean editContent(Long caseId, Long userId, Map<String, Object> fields, String reason) {
        if (fields == null || fields.isEmpty()) {
            throw conflict("INVALID_TARGET", "没有要修改的字段");
        }
        return tx.execute(status -> {
            Map<String, Object> flow = requireRunningFlowOfCase(caseId);
            Long flowId = asLong(flow.get("id"));
            Map<String, Object> node = requireEditableNode(flowId);
            boolean fallback = requireUploader(caseId, userId);

            Map<String, Object> before = parseJsonMap(String.valueOf(flow.get("baseline_json")));
            Map<String, Object> after = new LinkedHashMap<>(before);
            Map<String, Object> changed = new LinkedHashMap<>();
            boolean substantive = false;
            for (Map.Entry<String, Object> e : fields.entrySet()) {
                String key = e.getKey();
                Object oldValue = before.get(key);
                Object newValue = e.getValue();
                if (java.util.Objects.equals(String.valueOf(oldValue), String.valueOf(newValue))) {
                    continue;
                }
                after.put(key, newValue);
                Map<String, Object> diff = new LinkedHashMap<>();
                diff.put("from", oldValue);
                diff.put("to", newValue);
                changed.put(key, diff);
                if (SUBSTANTIVE_FIELDS.contains(key)) {
                    substantive = true;
                }
            }
            if (changed.isEmpty()) {
                return false;
            }
            String baseline = toJson(after);
            jdbc.update("""
                    UPDATE contract_flow SET baseline_json=?, baseline_hash=? WHERE id=?
                    """, baseline, sha256(baseline), flowId);
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("changed", changed);
            payload.put("substantive", substantive);
            payload.put("reason", reason == null ? "" : reason);
            addEvent(flowId, asLong(node.get("id")), EV_EDIT, userId, "USER", null, null,
                    payload, null);
            if (fallback) {
                Long anchor = asLong(node.get("id"));
                addEvent(flowId, anchor, EV_ADMIN_OVERRIDE, userId, "USER", null, null,
                        Map.of("nodeKey", String.valueOf(node.get("node_key")),
                                "reason", "CANDIDATE_FALLBACK"), null);
            }
            if (substantive) {
                triggerRerun(flowId, asLong(node.get("id")), "CONTENT_CHANGED");
            }
            return substantive;
        });
    }

    /**
     * 上传新版本 / 切换版本。只记录事件并更新 {@code flow.version_id}，
     * 文件本身由既有 document 上传接口负责。审批已开始后必须走撤回。
     */
    public void switchVersion(Long caseId, Long userId, Long versionId, String mode) {
        if (versionId == null) {
            throw conflict("INVALID_TARGET", "缺少版本号");
        }
        if (!EV_UPLOAD.equals(mode) && !EV_VERSION_SWITCH.equals(mode)) {
            throw conflict("INVALID_TARGET", "mode 只能是 UPLOAD 或 VERSION_SWITCH");
        }
        tx.executeWithoutResult(status -> {
            Map<String, Object> flow = requireRunningFlowOfCase(caseId);
            Long flowId = asLong(flow.get("id"));
            Map<String, Object> node = requireEditableNode(flowId);
            boolean fallback = requireUploader(caseId, userId);
            Integer exists = jdbc.queryForObject("""
                    SELECT COUNT(*) FROM contract_document
                    WHERE case_id=? AND version=? AND deleted=0
                    """, Integer.class, caseId, versionId);
            if (exists == null || exists == 0) {
                throw conflict("INVALID_TARGET", "该版本不存在");
            }
            Long previous = asLong(flow.get("version_id"));
            jdbc.update("UPDATE contract_flow SET version_id=? WHERE id=?", versionId, flowId);
            Long anchor = asLong(node.get("id"));
            addEvent(flowId, anchor, mode, userId, "USER", null, null,
                    Map.of("fromVersion", previous, "toVersion", versionId), null);
            if (fallback) {
                addEvent(flowId, anchor, EV_ADMIN_OVERRIDE, userId, "USER", null, null,
                        Map.of("nodeKey", String.valueOf(node.get("node_key")),
                                "reason", "CANDIDATE_FALLBACK"), null);
            }
            if (previous == null || !previous.equals(versionId)) {
                triggerRerun(flowId, anchor, "NEW_VERSION");
            }
        });
    }

    /** AGENT 节点合并重跑：运行中置标志，待跑则直接追加 AGENT_RERUN。 */
    private void triggerRerun(Long flowId, Long anchorNodeId, String trigger) {
        Long agentNodeId = nodeId(flowId, NODE_AGENT);
        if (agentNodeId == null) {
            return;
        }
        jdbc.update("UPDATE contract_flow_node SET pending_rerun=1 WHERE id=? AND state<>?",
                agentNodeId, NODE_DONE);
        addEvent(flowId, anchorNodeId, EV_AGENT_RERUN, null, "SYSTEM", null, null,
                Map.of("trigger", trigger), null);
    }

    /** 当前流程必须处于可编辑的节点（UPLOADER / AGENT），否则提示走撤回。 */
    private Map<String, Object> requireEditableNode(Long flowId) {
        Map<String, Object> node = currentActiveNode(flowId);
        if (node == null) {
            throw conflict("INVALID_STATE", "流程没有活跃节点");
        }
        String key = String.valueOf(node.get("node_key"));
        if (!NODE_UPLOADER.equals(key) && !NODE_AGENT.equals(key)) {
            throw conflict("NEED_WITHDRAW", "审批已开始，请先申请撤回再修改内容");
        }
        return node;
    }

    private Map<String, Object> requireUploaderNode(Long flowId, String message) {
        Map<String, Object> node = currentActiveNode(flowId);
        if (node == null || !NODE_UPLOADER.equals(node.get("node_key"))) {
            throw conflict("INVALID_STATE", message);
        }
        return node;
    }

    /** 案件当前 RUNNING 轮次，行锁。 */
    private Map<String, Object> requireRunningFlowOfCase(Long caseId) {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT * FROM contract_flow WHERE case_id=? AND state=? FOR UPDATE
                """, caseId, FLOW_RUNNING);
        if (rows.isEmpty()) {
            throw conflict("NO_RUNNING_FLOW", "该案件没有进行中的流程");
        }
        if (rows.size() > 1) {
            throw new IllegalStateException("案件 " + caseId + " 存在 " + rows.size()
                    + " 个 RUNNING 轮次，违反唯一不变量");
        }
        return rows.get(0);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseJsonMap(String json) {
        if (json == null || json.isBlank() || "{}".equals(json)) {
            return new LinkedHashMap<>();
        }
        try {
            return JSON.readValue(json, LinkedHashMap.class);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("baseline_json 解析失败", e);
        }
    }

    /** 候选组成员 user_id 列表（含 ADMIN 兜底）。 */
    public List<Long> candidates(Long flowId, String nodeKey) {
        Long caseId = caseIdOf(flowId);
        if (NODE_DEPT_APPROVAL.equals(nodeKey)) {
            Long deptId = jdbc.queryForObject(
                    "SELECT department_id FROM contract_case WHERE id=?", Long.class, caseId);
            return deptCandidates(deptId);
        }
        if (NODE_LEGAL_APPROVAL.equals(nodeKey)) {
            return legalCandidates();
        }
        return uploaderCandidates(caseId);
    }

    // ══════════════════════════════════════════════════════════════
    // 内部：创建与推进
    // ══════════════════════════════════════════════════════════════

    /**
     * 建一轮的节点链。
     *
     * <p>决策 18：只从 {@code startNode} 起建，<b>不建前置节点</b>。
     * 前置节点的"完成"属于上一轮，在新轮里补一行 DONE 只能填假时间或空时间，
     * 因此宁可不建；前端把缺的前几段显示为「上一轮已完成」。
     * {@code seq} 仍沿用 {@code NODE_CHAIN} 的原始下标，保证顺序语义不变。
     */
    private Long createFlow(Long caseId, Integer roundNo, Long versionId, String startNode,
                            Long parentFlowId, String baselineJson, Long startedBy) {
        String baseline = baselineJson == null ? "{}" : baselineJson;
        String hash = sha256(baseline);
        LocalDateTime now = LocalDateTime.now();
        jdbc.update("""
                INSERT INTO contract_flow
                (case_id,round_no,state,version_id,start_node,parent_flow_id,
                 baseline_json,baseline_hash,started_by,started_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """, caseId, roundNo, FLOW_RUNNING, versionId, startNode, parentFlowId,
                baseline, hash, startedBy, now);
        Long flowId = jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);

        int startSeq = seqOf(startNode);
        for (int i = startSeq; i < NODE_CHAIN.size(); i++) {
            String key = NODE_CHAIN.get(i);
            // 起点待认领，后续节点等前一节点 DONE 再翻（§1.2）
            String state = i == startSeq ? NODE_PENDING : NODE_WAITING;
            jdbc.update("""
                    INSERT INTO contract_flow_node
                    (flow_id,node_key,seq,state,assignee_id,candidate_group,entered_at,done_at,pending_rerun)
                    VALUES(?,?,?,?,?,?,?,?,0)
                    """, flowId, key, i, state, (Long) null, candidateGroupOf(caseId, key), now, null);
        }
        return flowId;
    }

    /** 当前节点完成后：推进到下一节点；末节点完成则流程 COMPLETED。 */
    private void advanceAfter(Long flowId, String completedNodeKey, Long actorId) {
        Integer seq = seqOf(completedNodeKey);
        if (seq == null) {
            return;
        }
        int nextSeq = seq + 1;
        if (nextSeq >= NODE_CHAIN.size()) {
            LocalDateTime now = LocalDateTime.now();
            jdbc.update("""
                    UPDATE contract_flow SET state=?, ended_at=?, end_reason=? WHERE id=?
                    """, FLOW_COMPLETED, now, "COMPLETED", flowId);
            addEvent(flowId, nodeId(flowId, completedNodeKey), EV_COMPLETE, actorId, "USER",
                    completedNodeKey, null, null, null);
            return;
        }
        String nextKey = NODE_CHAIN.get(nextSeq);
        Long nextNodeId = nodeId(flowId, nextKey);
        if (nextNodeId == null) {
            return;
        }
        enterNode(nextNodeId, actorId == null ? "SYSTEM" : "USER");
        addEvent(flowId, nextNodeId, EV_ENTER, actorId,
                actorId == null ? "SYSTEM" : "USER", completedNodeKey, nextKey, null, null);
    }

    /**
     * 把下一个节点翻成 {@code PENDING}。
     *
     * <p>允许两种来源：{@code WAITING}（正常推进）和 {@code VOID}（打回后重走，
     * 节点保留但事件不删）。其它状态意味着链上已有别的待办，属于数据违规，
     * 直接失败而不是覆盖。
     */
    private void enterNode(Long nodeId, String actorType) {
        int updated = jdbc.update("""
                UPDATE contract_flow_node
                SET state=?, assignee_id=NULL, claimed_at=NULL, claim_expires_at=NULL,
                    entered_at=?, done_at=NULL
                WHERE id=? AND state IN (?,?)
                """, NODE_PENDING, LocalDateTime.now(), nodeId, NODE_WAITING, NODE_VOID);
        if (updated == 0) {
            throw new IllegalStateException("节点 " + nodeId
                    + " 既不是 WAITING 也不是 VOID，无法推进：同一流程只能有一个待办节点");
        }
    }

    private void markDone(Map<String, Object> node) {
        jdbc.update("UPDATE contract_flow_node SET state=?, done_at=? WHERE id=?",
                NODE_DONE, LocalDateTime.now(), asLong(node.get("id")));
    }

    /** 节点完成时自动让未决撤回失效（§2.10 #1/#2/#3）。 */
    private void expirePendingWithdraw(Long flowId, String reason) {
        List<Map<String, Object>> pending = jdbc.queryForList(
                "SELECT id FROM contract_flow_withdraw WHERE flow_id=? AND state=? FOR UPDATE",
                flowId, WITHDRAW_PENDING);
        for (Map<String, Object> row : pending) {
            Long id = asLong(row.get("id"));
            jdbc.update("UPDATE contract_flow_withdraw SET state=?, decided_at=? WHERE id=?",
                    WITHDRAW_EXPIRED, LocalDateTime.now(), id);
            addEvent(flowId, anchorNodeId(flowId), EV_WITHDRAW_EXPIRE, null, "SYSTEM",
                    null, null, Map.of("withdrawId", id, "reason", reason), id);
        }
    }

    // ══════════════════════════════════════════════════════════════
    // 内部：查询与校验
    // ══════════════════════════════════════════════════════════════

    private void lockCase(Long caseId) {
        jdbc.queryForList("SELECT id FROM contract_case WHERE id=? FOR UPDATE", caseId);
    }

    private Map<String, Object> lockNode(Long nodeId) {
        return jdbc.queryForMap("SELECT * FROM contract_flow_node WHERE id=? FOR UPDATE", nodeId);
    }

    private Map<String, Object> requireRunningFlow(Long flowId) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT * FROM contract_flow WHERE id=? FOR UPDATE", flowId);
        if (rows.isEmpty()) {
            throw conflict("INVALID_STATE", "流程不存在");
        }
        Map<String, Object> flow = rows.get(0);
        if (!FLOW_RUNNING.equals(flow.get("state"))) {
            throw conflict("INVALID_STATE", "流程已结束");
        }
        return flow;
    }

    /**
     * 当前活跃节点。不做"取最小 seq"兜底：{@code PENDING} 与 {@code WAITING}
     * 语义不重叠，出现多个活跃节点说明数据已坏，必须报警而不是容错（§2.1）。
     */
    private Map<String, Object> currentActiveNode(Long flowId) {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT * FROM contract_flow_node
                WHERE flow_id=? AND state IN (?,?,?)
                ORDER BY seq ASC
                """, flowId, NODE_PENDING, NODE_CLAIMED, NODE_BLOCKED);
        if (rows.size() > 1) {
            throw new IllegalStateException("流程 " + flowId + " 存在 " + rows.size()
                    + " 个活跃节点，违反 PENDING 唯一不变量，请检查数据");
        }
        return rows.isEmpty() ? null : rows.get(0);
    }

    private Map<String, Object> nodeView(Long flowId, Map<String, Object> node) {
        Map<String, Object> view = new LinkedHashMap<>(node);
        String nodeKey = String.valueOf(node.get("node_key"));
        view.put("candidateCount", candidates(flowId, nodeKey).size());
        return view;
    }

    private void requireHolder(Map<String, Object> node, Long userId) {
        Long holder = asLong(node.get("assignee_id"));
        if (holder == null || !holder.equals(userId)) {
            if (!isAdmin(userId)) {
                throw forbidden("NOT_HOLDER", "只有当前持有者可以操作");
            }
        }
    }

    private void requireConfirmations(Long flowId) {
        long invalidatedAfter = lastConfirmationInvalidationId(flowId);
        for (String type : List.of(EV_CONFIRM_ELEMENTS, EV_CONFIRM_TIMELINE)) {
            Integer count = jdbc.queryForObject("""
                    SELECT COUNT(*) FROM contract_flow_event
                    WHERE flow_id=? AND event_type=? AND id>?
                    """, Integer.class, flowId, type, invalidatedAfter);
            if (count == null || count == 0) {
                throw conflict("CONFIRMATION_REQUIRED", "请先确认合同要素和履约日程");
            }
        }
    }

    /**
     * 确认事件的失效水位（§2.7 第 4 步：内容变更后旧的 CONFIRM_* 作废）。
     *
     * <p>取 {@code AGENT_RERUN} 与 {@code EDIT} 两类事件的最大 id：
     * 早于该水位写入的确认不再有效，必须重新确认。
     */
    private long lastConfirmationInvalidationId(Long flowId) {
        Long max = jdbc.queryForObject("""
                SELECT COALESCE(MAX(id),0) FROM contract_flow_event
                WHERE flow_id=? AND event_type IN (?,?)
                """, Long.class, flowId, EV_AGENT_RERUN, EV_EDIT);
        return max == null ? 0L : max;
    }

    /**
     * 上传人/签署节点的操作权校验。
     *
     * @return {@code true} 表示走了 ADMIN 回落（调用方必须写 ADMIN_OVERRIDE）
     */
    private boolean requireUploader(Long caseId, Long userId) {
        Integer count = jdbc.queryForObject("""
                SELECT COUNT(*) FROM contract_case
                WHERE id=? AND (creator_id=? OR maintainer_id=?)
                """, Integer.class, caseId, userId, userId);
        if (count != null && count > 0) {
            return false;
        }
        // 非 owner：只有 ADMIN 能走回落，且不算作正常候选资格（决策 14）
        if (isAdmin(userId)) {
            return true;
        }
        throw forbidden("NOT_CANDIDATE", "只有上传人可以操作该节点");
    }

    private boolean isCandidate(Long flowId, String nodeKey, Long userId) {
        return candidates(flowId, nodeKey).contains(userId);
    }

    /**
     * 部门审批候选组。为空就返回空——不回落 ADMIN（design v0.4 决策 14）：
     * 一旦回落，管理员等于所有部门的默认审批人，部门审批就形同虚设。
     * 管理员要用 {@link #forceClaim} 显式介入，并留下 ADMIN_OVERRIDE 事件。
     */
    private List<Long> deptCandidates(Long deptId) {
        if (deptId == null) {
            return List.of();
        }
        return jdbc.queryForList("""
                SELECT a.user_id FROM dept_approver a
                JOIN t_user u ON u.id=a.user_id AND u.status='ACTIVE'
                WHERE a.dept_id=?
                """, Long.class, deptId);
    }

    /** 法务组候选；为空返回空，理由同上。 */
    private List<Long> legalCandidates() {
        return jdbc.queryForList("""
                SELECT m.user_id FROM flow_role_member m
                JOIN t_user u ON u.id=m.user_id AND u.status='ACTIVE'
                WHERE m.role_code=?
                """, Long.class, ROLE_LEGAL);
    }

    /**
     * 上传人候选组：案件 creator / maintainer，另加 ADMIN。
     *
     * <p>本次只按决策 14 移除了 dept / legal 的回落，上传人节点保留 ADMIN：
     * 历史案件可能 creator_id / maintainer_id 都为空，去掉兜底会让这类案件
     * 完全无人可提交。若要一并收紧，需先做数据回填——已作为偏差上报。
     */
    private List<Long> uploaderCandidates(Long caseId) {
        List<Long> ids = new ArrayList<>(jdbc.queryForList("""
                SELECT id FROM t_user WHERE status='ACTIVE' AND id IN (
                    SELECT creator_id FROM contract_case WHERE id=?
                    UNION SELECT maintainer_id FROM contract_case WHERE id=?
                )
                """, Long.class, caseId, caseId));
        ids.addAll(adminIds());
        return ids.stream().distinct().toList();
    }

    private List<Long> adminIds() {
        return jdbc.queryForList(
                "SELECT id FROM t_user WHERE role='ADMIN' AND status='ACTIVE'", Long.class);
    }

    private boolean isAdmin(Long userId) {
        if (userId == null) {
            return false;
        }
        Integer count = jdbc.queryForObject(
                "SELECT COUNT(*) FROM t_user WHERE id=? AND role='ADMIN' AND status='ACTIVE'",
                Integer.class, userId);
        return count != null && count > 0;
    }

    private String candidateGroupOf(Long caseId, String nodeKey) {
        if (NODE_DEPT_APPROVAL.equals(nodeKey)) {
            Long deptId = jdbc.queryForObject(
                    "SELECT department_id FROM contract_case WHERE id=?", Long.class, caseId);
            return deptId == null ? GROUP_DEPT_PREFIX + "none" : GROUP_DEPT_PREFIX + deptId;
        }
        if (NODE_LEGAL_APPROVAL.equals(nodeKey)) {
            return GROUP_LEGAL;
        }
        if (NODE_AGENT.equals(nodeKey)) {
            return null;
        }
        return GROUP_OWNER;
    }

    private Long latestVersionId(Long caseId) {
        List<Long> ids = jdbc.queryForList("""
                SELECT version FROM contract_document
                WHERE case_id=? AND deleted=0
                ORDER BY version DESC LIMIT 1
                """, Long.class, caseId);
        return ids.isEmpty() ? null : ids.get(0);
    }

    private Long caseIdOf(Long flowId) {
        return jdbc.queryForObject("SELECT case_id FROM contract_flow WHERE id=?", Long.class, flowId);
    }

    /**
     * 事件的挂载节点（design v0.4 §1.3）：流程级事件没有天然节点时，
     * 挂当前活跃节点；流程已无活跃节点（全部 DONE）时挂 seq 最大的节点。
     * {@code node_id} 非空是 {@code uk_event} 真正生效的前提。
     */
    private Long anchorNodeId(Long flowId) {
        List<Map<String, Object>> active = jdbc.queryForList("""
                SELECT id FROM contract_flow_node
                WHERE flow_id=? AND state IN (?,?,?)
                ORDER BY seq ASC LIMIT 1
                """, flowId, NODE_PENDING, NODE_CLAIMED, NODE_BLOCKED);
        if (!active.isEmpty()) {
            return asLong(active.get(0).get("id"));
        }
        List<Map<String, Object>> last = jdbc.queryForList("""
                SELECT id FROM contract_flow_node WHERE flow_id=? ORDER BY seq DESC LIMIT 1
                """, flowId);
        if (last.isEmpty()) {
            throw new IllegalStateException("流程 " + flowId + " 没有任何节点，无法挂载事件");
        }
        return asLong(last.get(0).get("id"));
    }

    private Long nodeId(Long flowId, String nodeKey) {
        List<Long> ids = jdbc.queryForList(
                "SELECT id FROM contract_flow_node WHERE flow_id=? AND node_key=? LIMIT 1",
                Long.class, flowId, nodeKey);
        return ids.isEmpty() ? null : ids.get(0);
    }

    private Long firstNodeId(Long flowId, String nodeKey) {
        return nodeId(flowId, nodeKey);
    }

    private Integer seqOf(String nodeKey) {
        int idx = NODE_CHAIN.indexOf(nodeKey);
        return idx < 0 ? null : idx;
    }

    private void closeOpenClaim(Long nodeId, LocalDateTime now, String reason) {
        jdbc.update("""
                UPDATE contract_flow_claim
                SET released_at=?, release_reason=?
                WHERE node_id=? AND released_at IS NULL
                """, now, reason, nodeId);
    }

    // ══════════════════════════════════════════════════════════════
    // 内部：事件与工具
    // ══════════════════════════════════════════════════════════════

    private void addEvent(Long flowId, Long nodeId, String type, Long actorId, String actorType,
                          String fromNode, String toNode, Map<String, Object> payload, Long refId) {
        addEventRaw(flowId, nodeId, type, actorId, actorType, fromNode, toNode,
                payload == null ? null : toJson(payload), refId);
    }

    private void addEventRaw(Long flowId, Long nodeId, String type, Long actorId, String actorType,
                             String fromNode, String toNode, String json, Long refId) {
        // node_id 非空是 uk_event 生效的前提（design v0.4 决策 15）：NULL 会让
        // MySQL 唯一索引失效，重试时就无法去重。这里守一道，避免以后又漏挂。
        if (nodeId == null) {
            throw new IllegalStateException("事件 " + type + " 缺少 node_id，无法保证幂等");
        }
        // 带 ref_id 的事件是幂等的：重试命中 uk_event 时跳过，不视为错误。
        // 不带 ref_id 的事件（EDIT/CONFIRM_*/RETURN 等）必须真正写入，异常照常抛出。
        try {
            jdbc.update("""
                    INSERT INTO contract_flow_event
                    (flow_id,node_id,event_type,actor_id,actor_type,from_node,to_node,payload_json,ref_id)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    """, flowId, nodeId, type, actorId, actorType, fromNode, toNode, json, refId);
        } catch (DuplicateKeyException e) {
            if (refId == null) {
                throw e;
            }
            // 幂等重试：该 (flow,node,event,ref) 已记录过
        }
    }

    private String toJson(Map<String, Object> payload) {
        try {
            return JSON.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("无法序列化事件 payload", e);
        }
    }

    private String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    private LocalDateTime toLocalDateTime(Object value) {
        if (value == null) {
            return LocalDateTime.now();
        }
        if (value instanceof LocalDateTime ldt) {
            return ldt;
        }
        if (value instanceof java.sql.Timestamp ts) {
            return ts.toLocalDateTime();
        }
        return LocalDateTime.parse(String.valueOf(value), TS);
    }

    private static Long asLong(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Number n) {
            return n.longValue();
        }
        return Long.valueOf(String.valueOf(value));
    }

    private static ContractFlowException conflict(String reason, String message) {
        return new ContractFlowException(reason, 409, message);
    }

    private static ContractFlowException forbidden(String reason, String message) {
        return new ContractFlowException(reason, 403, message);
    }
}
