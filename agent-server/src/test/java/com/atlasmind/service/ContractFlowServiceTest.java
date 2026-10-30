package com.atlasmind.service;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static com.atlasmind.service.ContractFlowConstants.*;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 流程核心服务集成测试（真实 MySQL）。
 *
 * <p>覆盖 design 中最容易写错的三节：
 * §2.10 撤回 × 节点完成竞态真值表、§2.11 事务与并发硬约束、§2.6 撤回开新轮。
 */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ContractFlowServiceTest {

    private FlowTestDatabase db;
    private ContractFlowService service;

    private Long deptId;
    private Long uploaderId;
    private Long approverA;
    private Long approverB;
    private Long legalUser;
    private Long adminId;
    private Long caseId;

    @BeforeAll
    void startDatabase() {
        db = FlowTestDatabase.start();
        service = new ContractFlowService(db.jdbc(), db.tx());
    }

    @AfterAll
    void stopDatabase() {
        if (db != null) {
            db.close();
        }
    }

    @BeforeEach
    void seed() {
        db.reset();
        var jdbc = db.jdbc();
        jdbc.update("INSERT INTO department(name,code,is_default) VALUES('研发部','RD',0)");
        deptId = jdbc.queryForObject("SELECT id FROM department WHERE code='RD'", Long.class);
        insertUser("uploader", "USER", deptId);
        insertUser("approverA", "USER", deptId);
        insertUser("approverB", "USER", deptId);
        insertUser("legal", "USER", null);
        insertUser("admin", "ADMIN", deptId);
        uploaderId = userId("uploader");
        approverA = userId("approverA");
        approverB = userId("approverB");
        legalUser = userId("legal");
        adminId = userId("admin");

        jdbc.update("INSERT INTO dept_approver(dept_id,user_id) VALUES(?,?),(?,?)",
                deptId, approverA, deptId, approverB);
        jdbc.update("INSERT INTO flow_role_member(role_code,user_id) VALUES(?,?)",
                ROLE_LEGAL, legalUser);
        jdbc.update("""
                INSERT INTO contract_case(department_id,creator_id,maintainer_id,status)
                VALUES(?,?,?,'READY_FOR_REVIEW')
                """, deptId, uploaderId, uploaderId);
        caseId = jdbc.queryForObject("SELECT MAX(id) FROM contract_case", Long.class);
        jdbc.update("INSERT INTO contract_document(case_id,version,content_hash) VALUES(?,1,'h1')", caseId);
    }

    // ══════════════════════════════════════════════════════════════
    // 开启 / 提交
    // ══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("开启流程生成线性节点链，起始 UPLOADER 待上传人处理")
    void startFlowCreatesLinearChain() {
        Long flowId = service.startFlow(caseId, 1L, "{\"amount\":100}", uploaderId);
        List<Map<String, Object>> nodes = db.jdbc().queryForList(
                "SELECT node_key,seq,state FROM contract_flow_node WHERE flow_id=? ORDER BY seq", flowId);
        assertThat(nodes).extracting(n -> n.get("node_key"))
                .containsExactly("UPLOADER", "AGENT", "DEPT_APPROVAL", "LEGAL_APPROVAL", "SIGNING");
        // 不变量：只有 start_node 是 PENDING，其余 WAITING（design v0.4 §1.2）
        assertThat(nodes).extracting(n -> n.get("state"))
                .containsExactly(NODE_PENDING, NODE_WAITING, NODE_WAITING, NODE_WAITING, NODE_WAITING);
        assertThat(countPending(flowId)).isEqualTo(1);
        assertThat(db.jdbc().queryForObject(
                "SELECT baseline_hash FROM contract_flow WHERE id=?", String.class, flowId))
                .hasSize(64);
    }

    @Test
    @DisplayName("节点链推进过程中 PENDING 始终只有一个")
    void exactlyOnePendingThroughout() {
        Long flowId = reachDeptApproval();
        assertThat(countPending(flowId)).isEqualTo(1);
        claimAndApprove(flowId, NODE_DEPT_APPROVAL, approverA);
        assertThat(countPending(flowId)).isEqualTo(1);
        claimAndApprove(flowId, NODE_LEGAL_APPROVAL, legalUser);
        assertThat(countPending(flowId)).isEqualTo(1);
        assertThat(nodeState(flowId, NODE_SIGNING)).isEqualTo(NODE_PENDING);
    }

    @Test
    @DisplayName("同一案件第二个 RUNNING 轮次被拒绝")
    void cannotStartTwoRunningFlows() {
        service.startFlow(caseId, 1L, "{}", uploaderId);
        assertReason(() -> service.startFlow(caseId, 1L, "{}", uploaderId), "INVALID_STATE");
    }

    @Test
    @DisplayName("未确认要素和日程时提交被阻断")
    void submitRequiresConfirmations() {
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        Long uploaderNode = nodeId(flowId, NODE_UPLOADER);
        assertReason(() -> service.submit(uploaderNode, uploaderId), "CONFIRMATION_REQUIRED");

        confirm(flowId, EV_CONFIRM_ELEMENTS, uploaderId);
        assertReason(() -> service.submit(uploaderNode, uploaderId), "CONFIRMATION_REQUIRED");

        confirm(flowId, EV_CONFIRM_TIMELINE, uploaderId);
        service.submit(uploaderNode, uploaderId);
        assertThat(nodeState(flowId, NODE_UPLOADER)).isEqualTo(NODE_DONE);
        assertThat(nodeState(flowId, NODE_AGENT)).isEqualTo(NODE_PENDING);
    }

    @Test
    @DisplayName("候选组为空时提交返回 NO_APPROVER，即使存在 ADMIN 也不回落")
    void submitBlockedWhenNoApprover() {
        // 关键：ADMIN 仍然存在且活跃。v0.4 决策 14 要求不回落 ADMIN。
        db.jdbc().update("DELETE FROM dept_approver");
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        confirm(flowId, EV_CONFIRM_ELEMENTS, uploaderId);
        confirm(flowId, EV_CONFIRM_TIMELINE, uploaderId);
        assertReason(() -> service.submit(nodeId(flowId, NODE_UPLOADER), uploaderId), "NO_APPROVER");
    }

    @Test
    @DisplayName("法务组为空时提交同样返回 NO_APPROVER")
    void submitBlockedWhenNoLegalMember() {
        db.jdbc().update("DELETE FROM flow_role_member");
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        confirm(flowId, EV_CONFIRM_ELEMENTS, uploaderId);
        confirm(flowId, EV_CONFIRM_TIMELINE, uploaderId);
        assertReason(() -> service.submit(nodeId(flowId, NODE_UPLOADER), uploaderId), "NO_APPROVER");
    }

    @Test
    @DisplayName("非 owner 的 ADMIN 代提交上传人节点，写 ADMIN_OVERRIDE(CANDIDATE_FALLBACK)")
    void adminFallbackOnUploaderLeavesTrace() {
        // 案件 creator/maintainer 是 uploader，admin 不在其中
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        confirm(flowId, EV_CONFIRM_ELEMENTS, uploaderId);
        confirm(flowId, EV_CONFIRM_TIMELINE, uploaderId);
        service.submit(nodeId(flowId, NODE_UPLOADER), adminId);

        Map<String, Object> event = db.jdbc().queryForMap("""
                SELECT node_id,payload_json FROM contract_flow_event
                WHERE flow_id=? AND event_type='ADMIN_OVERRIDE' ORDER BY id DESC LIMIT 1
                """, flowId);
        assertThat(String.valueOf(event.get("payload_json"))).contains("CANDIDATE_FALLBACK");
        assertThat(((Number) event.get("node_id")).longValue())
                .isEqualTo(nodeId(flowId, NODE_UPLOADER));
        // owner 自己提交不会产生该事件
        assertThat(countEvents(flowId, EV_ADMIN_OVERRIDE)).isEqualTo(1);
    }

    @Test
    @DisplayName("owner 正常提交上传人节点不写 ADMIN_OVERRIDE")
    void ownerSubmitDoesNotLeaveOverride() {
        Long flowId = reachDeptApproval();
        assertThat(countEvents(flowId, EV_ADMIN_OVERRIDE)).isZero();
    }

    @Test
    @DisplayName("ADMIN 可强制认领并留下 ADMIN_OVERRIDE；非管理员不行")
    void forceClaimRequiresAdminAndLeavesTrace() {
        // 先走到部门审批，再把白名单清空：模拟"部门没配审批人"的真实场景
        Long flowId = reachDeptApproval();
        db.jdbc().update("DELETE FROM dept_approver");
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);

        assertReason(() -> service.forceClaim(deptNode, approverA), "NOT_ADMIN");
        service.forceClaim(deptNode, adminId);

        assertThat(nodeField(flowId, NODE_DEPT_APPROVAL, "assignee_id")).isEqualTo(adminId);
        assertThat(countEvents(flowId, EV_ADMIN_OVERRIDE)).isEqualTo(1);
        // 候选组仍为空：强制认领不会把 ADMIN 写进白名单
        assertThat(service.candidates(flowId, NODE_DEPT_APPROVAL)).isEmpty();
    }

    @Test
    @DisplayName("agent 运行中收到重跑请求后，旧确认作废，需重新确认")
    void rerunInvalidatesConfirmations() {
        Long flowId = reachDeptApproval();
        Long agentNode = nodeId(flowId, NODE_AGENT);
        // 模拟 agent 正在运行（节点回到 PENDING），此时收到内容变更
        rewindTo(flowId, NODE_AGENT);
        service.requestAgentRerun(flowId, "CONTENT_CHANGED");

        // 本次运行结束后因 pending_rerun 合并不推进，节点回到待跑
        service.onAgentFinished(flowId, 77L, agentNode, true, "{\"status\":\"SUCCEEDED\"}");
        assertThat(nodeState(flowId, NODE_AGENT)).isEqualTo(NODE_PENDING);

        // 回到上传人节点，旧的 CONFIRM_* 在 AGENT_RERUN 之前，不能被复用
        rewindTo(flowId, NODE_UPLOADER);
        assertReason(() -> service.submit(nodeId(flowId, NODE_UPLOADER), uploaderId), "CONFIRMATION_REQUIRED");
    }

    // ══════════════════════════════════════════════════════════════
    // 认领 / 通过
    // ══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("认领后其他候选人只能看，重复认领返回 ALREADY_CLAIMED")
    void claimIsExclusive() {
        Long flowId = reachDeptApproval();
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);
        service.claim(deptNode, approverA);
        assertThat(nodeField(flowId, NODE_DEPT_APPROVAL, "assignee_id")).isEqualTo(approverA);

        assertReason(() -> service.claim(deptNode, approverB), "ALREADY_CLAIMED");
        assertReason(() -> service.approve(deptNode, approverB, null), "NOT_HOLDER");
    }

    @Test
    @DisplayName("认领人不能同时在同流程持有两个节点")
    void cannotHoldTwoNodes() {
        Long flowId = reachDeptApproval();
        service.claim(nodeId(flowId, NODE_DEPT_APPROVAL), approverA);
        service.approve(nodeId(flowId, NODE_DEPT_APPROVAL), approverA, null);
        assertReason(() -> service.claim(nodeId(flowId, NODE_LEGAL_APPROVAL), approverA), "NOT_CANDIDATE");
    }

    @Test
    @DisplayName("非法候选人认领返回 NOT_CANDIDATE")
    void nonCandidateCannotClaim() {
        Long flowId = reachDeptApproval();
        assertReason(() -> service.claim(nodeId(flowId, NODE_DEPT_APPROVAL), legalUser), "NOT_CANDIDATE");
    }

    @Test
    @DisplayName("部门通过后推进到法务，法务通过后进入签署")
    void approvalAdvancesChain() {
        Long flowId = reachDeptApproval();
        claimAndApprove(flowId, NODE_DEPT_APPROVAL, approverA);
        assertThat(nodeState(flowId, NODE_LEGAL_APPROVAL)).isEqualTo(NODE_PENDING);

        service.claim(nodeId(flowId, NODE_LEGAL_APPROVAL), legalUser);
        service.approve(nodeId(flowId, NODE_LEGAL_APPROVAL), legalUser, "同意");
        assertThat(nodeState(flowId, NODE_SIGNING)).isEqualTo(NODE_PENDING);
    }

    @Test
    @DisplayName("签署是末节点：法务通过后流程仍 RUNNING，等待签署步骤收口")
    void signingIsLastNodeAndFlowStaysRunning() {
        Long flowId = reachDeptApproval();
        claimAndApprove(flowId, NODE_DEPT_APPROVAL, approverA);
        claimAndApprove(flowId, NODE_LEGAL_APPROVAL, legalUser);
        assertThat(nodeState(flowId, NODE_SIGNING)).isEqualTo(NODE_PENDING);
        // 签署节点由上传人持有，完成由签署件核对步骤（第 4 步）驱动，不伪造 COMPLETE
        assertThat(db.jdbc().queryForObject(
                "SELECT state FROM contract_flow WHERE id=?", String.class, flowId)).isEqualTo(FLOW_RUNNING);
        assertThat(countEvents(flowId, EV_COMPLETE)).isZero();
    }

    // ══════════════════════════════════════════════════════════════
    // 打回（§2.5）
    // ══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("法务跨节点打回上传人：中间节点 VOID，目标节点重新待认领")
    void returnVoidsIntermediateNodes() {
        Long flowId = reachDeptApproval();
        claimAndApprove(flowId, NODE_DEPT_APPROVAL, approverA);
        Long legalNode = nodeId(flowId, NODE_LEGAL_APPROVAL);
        service.claim(legalNode, legalUser);
        service.returnTo(legalNode, legalUser, NODE_UPLOADER, "金额有误，请重新上传");

        assertThat(nodeState(flowId, NODE_UPLOADER)).isEqualTo(NODE_PENDING);
        assertThat(nodeState(flowId, NODE_AGENT)).isEqualTo(NODE_VOID);
        assertThat(nodeState(flowId, NODE_DEPT_APPROVAL)).isEqualTo(NODE_VOID);
        assertThat(nodeState(flowId, NODE_LEGAL_APPROVAL)).isEqualTo(NODE_VOID);

        Map<String, Object> event = db.jdbc().queryForMap("""
                SELECT from_node,to_node,payload_json FROM contract_flow_event
                WHERE flow_id=? AND event_type='RETURN' ORDER BY id DESC LIMIT 1
                """, flowId);
        assertThat(event.get("from_node")).isEqualTo(NODE_LEGAL_APPROVAL);
        assertThat(event.get("to_node")).isEqualTo(NODE_UPLOADER);
        assertThat(String.valueOf(event.get("payload_json"))).contains("金额有误");
    }

    @Test
    @DisplayName("打回后重新走链：VOID 节点可被复活为 PENDING，且全程只有一个 PENDING")
    void returnThenReplayRevivesVoidNodes() {
        Long flowId = reachDeptApproval();
        claimAndApprove(flowId, NODE_DEPT_APPROVAL, approverA);
        Long legalNode = nodeId(flowId, NODE_LEGAL_APPROVAL);
        service.claim(legalNode, legalUser);
        service.returnTo(legalNode, legalUser, NODE_DEPT_APPROVAL, "部门再确认一下");
        assertThat(countPending(flowId)).isEqualTo(1);

        // 部门重新通过后，法务节点由 VOID 复活为 PENDING
        claimAndApprove(flowId, NODE_DEPT_APPROVAL, approverB);
        assertThat(nodeState(flowId, NODE_LEGAL_APPROVAL)).isEqualTo(NODE_PENDING);
        assertThat(countPending(flowId)).isEqualTo(1);
    }

    @Test
    @DisplayName("只能打回前序节点")
    void returnTargetMustBeEarlier() {
        Long flowId = reachDeptApproval();
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);
        service.claim(deptNode, approverA);
        assertReason(() -> service.returnTo(deptNode, approverA, NODE_LEGAL_APPROVAL, "理由足够长"),
                "INVALID_TARGET");
        assertReason(() -> service.returnTo(deptNode, approverA, NODE_UPLOADER, " "),
                "INVALID_TARGET");
    }

    // ══════════════════════════════════════════════════════════════
    // 撤回开新轮（§2.6）与竞态真值表（§2.10）
    // ══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("撤回批准开新一轮：旧轮 CANCELLED，新轮 parent_flow_id 指向旧轮且目标前节点 DONE")
    void withdrawApprovalStartsNewRound() {
        Long flowId = reachDeptApproval();
        claimAndApprove(flowId, NODE_DEPT_APPROVAL, approverA);
        Long legalNode = nodeId(flowId, NODE_LEGAL_APPROVAL);
        service.claim(legalNode, legalUser);
        // 上传人申请撤回（当前持有者是法务）
        Long withdrawId = service.requestWithdraw(flowId, uploaderId, NODE_UPLOADER, "金额写错了");
        service.decideWithdraw(withdrawId, legalUser, true, null);

        Map<String, Object> oldFlow = db.jdbc().queryForMap(
                "SELECT state,end_reason FROM contract_flow WHERE id=?", flowId);
        assertThat(oldFlow.get("state")).isEqualTo(FLOW_CANCELLED);
        assertThat(oldFlow.get("end_reason")).isEqualTo(END_WITHDRAWN);

        Map<String, Object> newFlow = db.jdbc().queryForMap(
                "SELECT id,round_no,parent_flow_id,start_node FROM contract_flow WHERE case_id=? AND round_no=2",
                caseId);
        assertThat(newFlow.get("parent_flow_id")).isEqualTo(flowId);
        assertThat(newFlow.get("start_node")).isEqualTo(NODE_UPLOADER);
        Long newFlowId = ((Number) newFlow.get("id")).longValue();
        // 从上传人重走：起点 PENDING，其余 WAITING
        assertThat(nodeState(newFlowId, NODE_UPLOADER)).isEqualTo(NODE_PENDING);
        assertThat(nodeState(newFlowId, NODE_DEPT_APPROVAL)).isEqualTo(NODE_WAITING);
        // 旧轮节点不被改写
        assertThat(nodeState(flowId, NODE_LEGAL_APPROVAL)).isEqualTo(NODE_CLAIMED);
    }

    @Test
    @DisplayName("撤回目标为法务时：新轮只从法务建链，前置节点不建（决策 18）")
    void withdrawRestartFromLaterNodeSkipsEarlierNodes() {
        Long flowId = reachDeptApproval();
        claimAndApprove(flowId, NODE_DEPT_APPROVAL, approverA);
        Long legalNode = nodeId(flowId, NODE_LEGAL_APPROVAL);
        service.claim(legalNode, legalUser);
        // 上传人申请撤回、目标法务；当前持有者法务批准（申请人≠持有者）
        Long withdrawId = service.requestWithdraw(flowId, uploaderId, NODE_LEGAL_APPROVAL, "补充说明");
        service.decideWithdraw(withdrawId, legalUser, true, null);

        Long newFlowId = db.jdbc().queryForObject(
                "SELECT id FROM contract_flow WHERE case_id=? AND round_no=2", Long.class, caseId);
        // 前置节点在本轮不存在，不能伪造 DONE + done_at
        assertThat(countNodes(newFlowId)).isEqualTo(2);
        assertThat(nodeKeys(newFlowId)).containsExactly(NODE_LEGAL_APPROVAL, NODE_SIGNING);
        assertThat(nodeState(newFlowId, NODE_LEGAL_APPROVAL)).isEqualTo(NODE_PENDING);
        assertThat(nodeState(newFlowId, NODE_SIGNING)).isEqualTo(NODE_WAITING);
        assertThat(countPending(newFlowId)).isEqualTo(1);
        // seq 沿用原始序号，顺序语义不变
        assertThat(nodeSeq(newFlowId, NODE_LEGAL_APPROVAL)).isEqualTo(3);
        assertThat(nodeSeq(newFlowId, NODE_SIGNING)).isEqualTo(4);
    }

    @Test
    @DisplayName("真值表 #1/#2：撤回待批时节点被通过/打回，撤回置 EXPIRED")
    void pendingWithdrawExpiresWhenNodeCompletes() {
        Long flowId = reachDeptApproval();
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);
        service.claim(deptNode, approverA);

        Long approvedWithdraw = service.requestWithdraw(flowId, uploaderId, NODE_UPLOADER, "改金额");
        service.approve(deptNode, approverA, null);
        assertThat(withdrawState(approvedWithdraw)).isEqualTo(WITHDRAW_EXPIRED);
        assertThat(countEvents(flowId, EV_WITHDRAW_EXPIRE)).isEqualTo(1);

        // 再走一次，用打回触发
        Long legalNode = nodeId(flowId, NODE_LEGAL_APPROVAL);
        service.claim(legalNode, legalUser);
        Long returnedWithdraw = service.requestWithdraw(flowId, uploaderId, NODE_UPLOADER, "改条款");
        service.returnTo(legalNode, legalUser, NODE_UPLOADER, "条款需要重写");
        assertThat(withdrawState(returnedWithdraw)).isEqualTo(WITHDRAW_EXPIRED);
        assertThat(countEvents(flowId, EV_WITHDRAW_EXPIRE)).isEqualTo(2);
    }

    @Test
    @DisplayName("真值表 #3：撤回待批时流程被取消，撤回置 EXPIRED")
    void pendingWithdrawExpiresWhenFlowCancelled() {
        Long flowId = reachDeptApproval();
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);
        // 让待认领节点超过 6 小时
        db.jdbc().update("UPDATE contract_flow_node SET entered_at=? WHERE id=?",
                Timestamp.valueOf(LocalDateTime.now().minusHours(7)), deptNode);
        Long withdrawId = service.requestWithdraw(flowId, uploaderId, NODE_UPLOADER, "想改");
        service.cancel(flowId, uploaderId, "超时取消");
        assertThat(withdrawState(withdrawId)).isEqualTo(WITHDRAW_EXPIRED);
        assertThat(db.jdbc().queryForObject("SELECT state FROM contract_flow WHERE id=?",
                String.class, flowId)).isEqualTo(FLOW_CANCELLED);
    }

    @Test
    @DisplayName("真值表 #4：申请人自批被拒，需转管理员")
    void requesterCannotApproveOwnWithdraw() {
        Long flowId = reachDeptApproval();
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);
        service.claim(deptNode, approverA);
        Long withdrawId = service.requestWithdraw(flowId, approverA, NODE_DEPT_APPROVAL, "改一下");
        assertReason(() -> service.decideWithdraw(withdrawId, approverA, true, null),
                "SELF_APPROVE_FORBIDDEN");
        // 管理员可代为批准
        service.decideWithdraw(withdrawId, adminId, true, "管理员同意");
        assertThat(withdrawState(withdrawId)).isEqualTo(WITHDRAW_APPROVED);
    }

    @Test
    @DisplayName("真值表 #5：申请人被移出候选组后仍可由持有者批准")
    void requesterRemovalDoesNotBlockDecision() {
        Long flowId = reachDeptApproval();
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);
        service.claim(deptNode, approverA);
        Long withdrawId = service.requestWithdraw(flowId, approverB, NODE_DEPT_APPROVAL, "补充材料");
        db.jdbc().update("DELETE FROM dept_approver WHERE user_id=?", approverB);
        service.decideWithdraw(withdrawId, approverA, true, null);
        assertThat(withdrawState(withdrawId)).isEqualTo(WITHDRAW_APPROVED);
    }

    @Test
    @DisplayName("真值表 #7：撤回后同版本可开新轮（取消原因是 WITHDRAWN 不算冲突）")
    void sameVersionAllowedAfterWithdraw() {
        Long flowId = reachDeptApproval();
        claimAndApprove(flowId, NODE_DEPT_APPROVAL, approverA);
        Long legalNode = nodeId(flowId, NODE_LEGAL_APPROVAL);
        service.claim(legalNode, legalUser);
        Long withdrawId = service.requestWithdraw(flowId, uploaderId, NODE_UPLOADER, "改金额");
        service.decideWithdraw(withdrawId, legalUser, true, null);

        // 撤回批准会自动开新轮，且沿用同一 version_id（不算"同版本不能重开"）
        Map<String, Object> newFlow = db.jdbc().queryForMap(
                "SELECT id,version_id,parent_flow_id FROM contract_flow WHERE case_id=? AND round_no=2",
                caseId);
        assertThat(((Number) newFlow.get("version_id")).longValue()).isEqualTo(1L);
        assertThat(newFlow.get("parent_flow_id")).isEqualTo(flowId);

        // 若这轮再被取消（非撤回），同版本就不能重开
        db.jdbc().update("UPDATE contract_flow SET state='CANCELLED', end_reason='CANCELLED' WHERE id=?",
                ((Number) newFlow.get("id")).longValue());
        assertReason(() -> service.startFlow(caseId, 1L, "{}", uploaderId), "VERSION_CANCELLED");
    }

    @Test
    @DisplayName("真值表 #8：并发撤回只有一个成功，另一个返回 WITHDRAW_PENDING_EXISTS")
    void concurrentWithdrawOnlyOnePending() throws Exception {
        Long flowId = reachDeptApproval();
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);
        service.claim(deptNode, approverA);

        ExecutorService pool = Executors.newFixedThreadPool(2);
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch go = new CountDownLatch(1);
        Callable<String> task = () -> {
            ready.countDown();
            go.await(5, TimeUnit.SECONDS);
            try {
                service.requestWithdraw(flowId, uploaderId, NODE_UPLOADER, "并发申请");
                return "OK";
            } catch (ContractFlowException e) {
                return e.getReason();
            }
        };
        Future<String> f1 = pool.submit(task);
        Future<String> f2 = pool.submit(task);
        ready.await(5, TimeUnit.SECONDS);
        go.countDown();
        List<String> results = List.of(f1.get(10, TimeUnit.SECONDS), f2.get(10, TimeUnit.SECONDS));
        pool.shutdown();

        assertThat(results).containsExactlyInAnyOrder("OK", "WITHDRAW_PENDING_EXISTS");
        assertThat(db.jdbc().queryForObject(
                "SELECT COUNT(*) FROM contract_flow_withdraw WHERE flow_id=? AND state='PENDING'",
                Integer.class, flowId)).isEqualTo(1);
    }

    @Test
    @DisplayName("非持有者不能批准撤回")
    void onlyHolderCanDecideWithdraw() {
        Long flowId = reachDeptApproval();
        service.claim(nodeId(flowId, NODE_DEPT_APPROVAL), approverA);
        Long withdrawId = service.requestWithdraw(flowId, uploaderId, NODE_UPLOADER, "改金额");
        assertReason(() -> service.decideWithdraw(withdrawId, approverB, true, null), "NOT_HOLDER");
    }

    @Test
    @DisplayName("撤回被驳回后流程不变，可再次申请")
    void rejectedWithdrawKeepsFlowRunning() {
        Long flowId = reachDeptApproval();
        service.claim(nodeId(flowId, NODE_DEPT_APPROVAL), approverA);
        Long withdrawId = service.requestWithdraw(flowId, uploaderId, NODE_UPLOADER, "先试试");
        service.decideWithdraw(withdrawId, approverA, false, "内容没问题");
        assertThat(withdrawState(withdrawId)).isEqualTo(WITHDRAW_REJECTED);
        assertThat(db.jdbc().queryForObject("SELECT state FROM contract_flow WHERE id=?",
                String.class, flowId)).isEqualTo(FLOW_RUNNING);
        // 可以再次申请
        Long second = service.requestWithdraw(flowId, uploaderId, NODE_UPLOADER, "再申请一次");
        assertThat(second).isNotNull();
    }

    // ══════════════════════════════════════════════════════════════
    // 取消（§2.4）
    // ══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("待认领未满 6 小时不可取消，返回剩余时间")
    void cancelBlockedBeforeSixHours() {
        Long flowId = reachDeptApproval();
        Map<String, Object> eligibility = service.cancelEligibility(flowId);
        assertThat(eligibility.get("allowed")).isEqualTo(false);
        assertThat(eligibility.get("reasonCode")).isEqualTo("PENDING_TOO_EARLY");
        assertThat(eligibility).containsKey("remainingMinutes");
        assertReason(() -> service.cancel(flowId, uploaderId, "急"), "CANCEL_NOT_ALLOWED");
    }

    @Test
    @DisplayName("待认领满 6 小时可取消，取消后不可重开同版本")
    void cancelAllowedAfterSixHours() {
        Long flowId = reachDeptApproval();
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);
        db.jdbc().update("UPDATE contract_flow_node SET entered_at=? WHERE id=?",
                Timestamp.valueOf(LocalDateTime.now().minusHours(6).minusMinutes(1)), deptNode);
        assertThat(service.cancelEligibility(flowId).get("allowed")).isEqualTo(true);

        service.cancel(flowId, uploaderId, "没人处理");
        assertThat(db.jdbc().queryForObject("SELECT state FROM contract_flow WHERE id=?",
                String.class, flowId)).isEqualTo(FLOW_CANCELLED);
        assertThat(db.jdbc().queryForObject("SELECT end_reason FROM contract_flow WHERE id=?",
                String.class, flowId)).isEqualTo(END_CANCELLED);

        // 同版本不能重开
        assertReason(() -> service.startFlow(caseId, 1L, "{}", uploaderId), "VERSION_CANCELLED");
        // 换版本可以
        db.jdbc().update("INSERT INTO contract_document(case_id,version,content_hash) VALUES(?,2,'h2')", caseId);
        Long newFlow = service.startFlow(caseId, 2L, "{}", uploaderId);
        assertThat(newFlow).isNotNull();
    }

    @Test
    @DisplayName("已有持有者处理时不可取消")
    void cancelBlockedWhenClaimed() {
        Long flowId = reachDeptApproval();
        service.claim(nodeId(flowId, NODE_DEPT_APPROVAL), approverA);
        Map<String, Object> eligibility = service.cancelEligibility(flowId);
        assertThat(eligibility.get("allowed")).isEqualTo(false);
        assertThat(eligibility.get("reasonCode")).isEqualTo("HOLDER_PROCESSING");
    }

    @Test
    @DisplayName("agent 失败可取消")
    void cancelAllowedWhenAgentBlocked() {
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        confirm(flowId, EV_CONFIRM_ELEMENTS, uploaderId);
        confirm(flowId, EV_CONFIRM_TIMELINE, uploaderId);
        service.submit(nodeId(flowId, NODE_UPLOADER), uploaderId);
        Long agentNode = nodeId(flowId, NODE_AGENT);
        service.onAgentFinished(flowId, 42L, agentNode, false, "{\"reason\":\"TIMEOUT\"}");
        assertThat(nodeState(flowId, NODE_AGENT)).isEqualTo(NODE_BLOCKED);

        Map<String, Object> eligibility = service.cancelEligibility(flowId);
        assertThat(eligibility.get("allowed")).isEqualTo(true);
        assertThat(eligibility.get("reasonCode")).isEqualTo("AGENT_FAILED");
        service.cancel(flowId, uploaderId, "agent 失败");
        assertThat(countEvents(flowId, EV_CANCEL)).isEqualTo(1);
    }

    // ══════════════════════════════════════════════════════════════
    // agent 推进（§2.9）
    // ══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("agent 成功推进到部门审批；重复回报同一 run 幂等")
    void agentSuccessAdvancesOnce() {
        Long flowId = reachDeptApproval();
        Long agentNode = nodeId(flowId, NODE_AGENT);
        // 恢复 agent 节点为活跃，模拟运行中（后续节点回到 WAITING）
        rewindTo(flowId, NODE_AGENT);

        service.onAgentFinished(flowId, 501L, agentNode, true, "{\"status\":\"SUCCEEDED\"}");
        assertThat(nodeState(flowId, NODE_AGENT)).isEqualTo(NODE_DONE);
        assertThat(nodeState(flowId, NODE_DEPT_APPROVAL)).isEqualTo(NODE_PENDING);

        // 重复回报：不改变状态、不重复写事件（按 ref_id 统计第一次回报）
        service.onAgentFinished(flowId, 501L, agentNode, true, "{\"status\":\"SUCCEEDED\"}");
        assertThat(countEventsByRef(flowId, EV_AGENT_RUN, 501L)).isEqualTo(1);
        assertThat(nodeState(flowId, NODE_AGENT)).isEqualTo(NODE_DONE);
    }

    @Test
    @DisplayName("agent 失败置 BLOCKED 并写 AGENT_FAIL")
    void agentFailureBlocksNode() {
        Long flowId = reachDeptApproval();
        Long agentNode = nodeId(flowId, NODE_AGENT);
        rewindTo(flowId, NODE_AGENT);
        service.onAgentFinished(flowId, 502L, agentNode, false, "{\"reason\":\"TIMEOUT\"}");
        assertThat(nodeState(flowId, NODE_AGENT)).isEqualTo(NODE_BLOCKED);
        assertThat(countEvents(flowId, EV_AGENT_FAIL)).isEqualTo(1);
    }

    @Test
    @DisplayName("运行中收到重跑请求：成功后合并为一次 AGENT_RERUN，节点回到待跑")
    void rerunMergesWhileRunning() {
        Long flowId = reachDeptApproval();
        Long agentNode = nodeId(flowId, NODE_AGENT);
        rewindTo(flowId, NODE_AGENT);
        service.requestAgentRerun(flowId, "CONTENT_CHANGED");
        service.onAgentFinished(flowId, 503L, agentNode, true, "{}");
        assertThat(nodeState(flowId, NODE_AGENT)).isEqualTo(NODE_PENDING);
        assertThat(nodeField(flowId, NODE_AGENT, "pending_rerun")).isEqualTo(0);
        assertThat(countEvents(flowId, EV_AGENT_RERUN)).isEqualTo(2);
    }

    // ══════════════════════════════════════════════════════════════
    // §2.11 事务硬约束
    // ══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("动作失败时事件不落库（同事务回滚），不吞异常")
    void failedActionRollsBackEvents() {
        Long flowId = reachDeptApproval();
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);
        service.claim(deptNode, approverA);
        long before = countEvents(flowId, EV_APPROVE);
        assertReason(() -> service.approve(deptNode, approverB, null), "NOT_HOLDER");
        assertThat(countEvents(flowId, EV_APPROVE)).isEqualTo(before);
        assertThat(nodeState(flowId, NODE_DEPT_APPROVAL)).isEqualTo(NODE_CLAIMED);
    }

    @Test
    @DisplayName("并发认领只有一个成功")
    void concurrentClaimOnlyOneWins() throws Exception {
        Long flowId = reachDeptApproval();
        Long deptNode = nodeId(flowId, NODE_DEPT_APPROVAL);

        ExecutorService pool = Executors.newFixedThreadPool(2);
        CountDownLatch go = new CountDownLatch(1);
        java.util.function.Function<Long, Callable<String>> task = uid -> () -> {
            go.await(5, TimeUnit.SECONDS);
            try {
                service.claim(deptNode, uid);
                return "OK";
            } catch (ContractFlowException e) {
                return e.getReason();
            }
        };
        Future<String> f1 = pool.submit(task.apply(approverA));
        Future<String> f2 = pool.submit(task.apply(approverB));
        go.countDown();
        List<String> results = List.of(f1.get(10, TimeUnit.SECONDS), f2.get(10, TimeUnit.SECONDS));
        pool.shutdown();

        assertThat(results).containsExactlyInAnyOrder("OK", "ALREADY_CLAIMED");
        assertThat(db.jdbc().queryForObject(
                "SELECT COUNT(*) FROM contract_flow_node WHERE id=? AND assignee_id IS NOT NULL",
                Integer.class, deptNode)).isEqualTo(1);
    }

    @Test
    @DisplayName("事件唯一键挡住同 (flow,node,event,ref) 的重复写入")
    void eventUniqueKeyPreventsDuplicate() {
        Long flowId = reachDeptApproval();
        Long agentNode = nodeId(flowId, NODE_AGENT);
        rewindTo(flowId, NODE_AGENT);
        service.onAgentFinished(flowId, 900L, agentNode, false, "{}");
        rewindTo(flowId, NODE_AGENT);
        service.onAgentFinished(flowId, 900L, agentNode, false, "{}");
        assertThat(db.jdbc().queryForObject("""
                SELECT COUNT(*) FROM contract_flow_event
                WHERE flow_id=? AND node_id=? AND event_type='AGENT_FAIL' AND ref_id=900
                """, Integer.class, flowId, agentNode)).isEqualTo(1);
    }

    // ══════════════════════════════════════════════════════════════
    // 内容类动作：confirm-* / edit / version（§3.1 第 3 步）
    // ══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("确认要素/日程：失效前重复点击幂等，只写一条事件")
    void confirmIsIdempotentBeforeInvalidation() {
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        service.confirmElements(caseId, uploaderId);
        service.confirmElements(caseId, uploaderId);
        service.confirmTimeline(caseId, uploaderId);
        service.confirmTimeline(caseId, uploaderId);

        assertThat(countEvents(flowId, EV_CONFIRM_ELEMENTS)).isEqualTo(1);
        assertThat(countEvents(flowId, EV_CONFIRM_TIMELINE)).isEqualTo(1);
        // 两条确认都挂在上传人节点上（node_id 非空）
        assertThat(db.jdbc().queryForObject("""
                SELECT COUNT(*) FROM contract_flow_event
                WHERE flow_id=? AND node_id=? AND event_type IN (?,?)
                """, Integer.class, flowId, nodeId(flowId, NODE_UPLOADER),
                EV_CONFIRM_ELEMENTS, EV_CONFIRM_TIMELINE)).isEqualTo(2);
    }

    @Test
    @DisplayName("非上传人不能确认；确认齐全后可直接提交")
    void confirmRequiresUploader() {
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        assertReason(() -> service.confirmElements(caseId, approverA), "NOT_CANDIDATE");

        service.confirmElements(caseId, uploaderId);
        service.confirmTimeline(caseId, uploaderId);
        service.submit(nodeId(flowId, NODE_UPLOADER), uploaderId);
        assertThat(nodeState(flowId, NODE_AGENT)).isEqualTo(NODE_PENDING);
    }

    @Test
    @DisplayName("审批开始后不能再确认：已离开上传人节点")
    void confirmRejectedOutsideUploaderNode() {
        reachDeptApproval();
        assertReason(() -> service.confirmElements(caseId, uploaderId), "INVALID_STATE");
        assertReason(() -> service.confirmTimeline(caseId, uploaderId), "INVALID_STATE");
    }

    @Test
    @DisplayName("修改非实质字段：写 EDIT 更新基线，但不触发重跑")
    void editNonSubstantiveDoesNotRerun() {
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        boolean substantive = service.editContent(caseId, uploaderId,
                Map.of("remark", "补充说明"), "校对错别字");

        assertThat(substantive).isFalse();
        assertThat(countEvents(flowId, EV_EDIT)).isEqualTo(1);
        assertThat(countEvents(flowId, EV_AGENT_RERUN)).isZero();
        assertThat(db.jdbc().queryForObject(
                "SELECT baseline_json FROM contract_flow WHERE id=?", String.class, flowId))
                .contains("remark");
    }

    @Test
    @DisplayName("修改实质字段：更新基线、触发重跑，并让旧确认失效")
    void editSubstantiveTriggersRerunAndInvalidatesConfirmation() {
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        service.confirmElements(caseId, uploaderId);
        service.confirmTimeline(caseId, uploaderId);

        boolean substantive = service.editContent(caseId, uploaderId,
                Map.of("amount", 5000), "金额变更");

        assertThat(substantive).isTrue();
        assertThat(countEvents(flowId, EV_EDIT)).isEqualTo(1);
        assertThat(countEvents(flowId, EV_AGENT_RERUN)).isEqualTo(1);
        assertThat(db.jdbc().queryForObject("""
                SELECT pending_rerun FROM contract_flow_node WHERE flow_id=? AND node_key=?
                """, Integer.class, flowId, NODE_AGENT)).isEqualTo(1);
        // EDIT 事件水位之后，之前的确认不再算数
        assertReason(() -> service.submit(nodeId(flowId, NODE_UPLOADER), uploaderId),
                "CONFIRMATION_REQUIRED");
    }

    @Test
    @DisplayName("提交相同值不算修改，不写任何事件")
    void editNoopWritesNothing() {
        Long flowId = service.startFlow(caseId, 1L, "{\"amount\":100}", uploaderId);
        boolean substantive = service.editContent(caseId, uploaderId, Map.of("amount", 100), null);

        assertThat(substantive).isFalse();
        assertThat(countEvents(flowId, EV_EDIT)).isZero();
    }

    @Test
    @DisplayName("审批阶段修改被拒：必须走撤回")
    void editRejectedAfterApprovalStarted() {
        reachDeptApproval();
        assertReason(() -> service.editContent(caseId, uploaderId, Map.of("amount", 1), null),
                "NEED_WITHDRAW");
    }

    @Test
    @DisplayName("空修改直接拒绝")
    void editEmptyFieldsRejected() {
        service.startFlow(caseId, 1L, "{}", uploaderId);
        assertReason(() -> service.editContent(caseId, uploaderId, Map.of(), null),
                "INVALID_TARGET");
    }

    @Test
    @DisplayName("切换版本：更新 flow.version_id 并触发重跑")
    void switchVersionUpdatesFlowAndTriggersRerun() {
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        db.jdbc().update(
                "INSERT INTO contract_document(case_id,version,content_hash) VALUES(?,2,'h2')", caseId);

        service.switchVersion(caseId, uploaderId, 2L, EV_VERSION_SWITCH);

        assertThat(db.jdbc().queryForObject(
                "SELECT version_id FROM contract_flow WHERE id=?", Long.class, flowId)).isEqualTo(2L);
        assertThat(countEvents(flowId, EV_VERSION_SWITCH)).isEqualTo(1);
        assertThat(countEvents(flowId, EV_AGENT_RERUN)).isEqualTo(1);
    }

    @Test
    @DisplayName("切换版本参数校验：非法 mode / 不存在版本")
    void switchVersionRejectsBadInput() {
        service.startFlow(caseId, 1L, "{}", uploaderId);
        assertReason(() -> service.switchVersion(caseId, uploaderId, 1L, "RENAME"), "INVALID_TARGET");
        assertReason(() -> service.switchVersion(caseId, uploaderId, 99L, EV_UPLOAD), "INVALID_TARGET");
    }

    @Test
    @DisplayName("审批中切换版本被拒：必须走撤回")
    void switchVersionRejectedAfterApprovalStarted() {
        reachDeptApproval();
        assertReason(() -> service.switchVersion(caseId, uploaderId, 1L, EV_UPLOAD), "NEED_WITHDRAW");
    }

    // ══════════════════════════════════════════════════════════════
    // helpers
    // ══════════════════════════════════════════════════════════════

    /** 走到部门审批待认领：开启 → 确认 → 提交 → agent 完成。 */
    private Long reachDeptApproval() {
        Long flowId = service.startFlow(caseId, 1L, "{}", uploaderId);
        confirm(flowId, EV_CONFIRM_ELEMENTS, uploaderId);
        confirm(flowId, EV_CONFIRM_TIMELINE, uploaderId);
        service.submit(nodeId(flowId, NODE_UPLOADER), uploaderId);
        Long agentNode = nodeId(flowId, NODE_AGENT);
        service.onAgentFinished(flowId, 100L, agentNode, true, "{}");
        return flowId;
    }

    /**
     * 把某个节点手工置回 PENDING，并把链上它之后的节点全部置回 WAITING。
     * 用于模拟"agent 运行中 / 回到上传人"等场景，同时维持 PENDING 唯一不变量。
     */
    private void rewindTo(Long flowId, String nodeKey) {
        int seq = NODE_CHAIN.indexOf(nodeKey);
        db.jdbc().update("""
                UPDATE contract_flow_node SET state=?, assignee_id=NULL, done_at=NULL
                WHERE flow_id=? AND seq>?
                """, NODE_WAITING, flowId, seq);
        db.jdbc().update("""
                UPDATE contract_flow_node SET state=?, assignee_id=NULL, done_at=NULL
                WHERE flow_id=? AND node_key=?
                """, NODE_PENDING, flowId, nodeKey);
    }

    private void claimAndApprove(Long flowId, String nodeKey, Long userId) {
        Long node = nodeId(flowId, nodeKey);
        service.claim(node, userId);
        service.approve(node, userId, null);
    }

    private void insertUser(String username, String role, Long deptId) {
        db.jdbc().update("INSERT INTO t_user(username,role,department_id,status) VALUES(?,?,?,'ACTIVE')",
                username, role, deptId);
    }

    private Long userId(String username) {
        return db.jdbc().queryForObject("SELECT id FROM t_user WHERE username=?", Long.class, username);
    }

    private Long onlyFlowId() {
        return db.jdbc().queryForObject("SELECT MAX(id) FROM contract_flow", Long.class);
    }

    private Long nodeId(Long flowId, String nodeKey) {
        return db.jdbc().queryForObject(
                "SELECT id FROM contract_flow_node WHERE flow_id=? AND node_key=?",
                Long.class, flowId, nodeKey);
    }

    private String nodeState(Long flowId, String nodeKey) {
        return db.jdbc().queryForObject(
                "SELECT state FROM contract_flow_node WHERE flow_id=? AND node_key=?",
                String.class, flowId, nodeKey);
    }

    private Object nodeField(Long flowId, String nodeKey, String column) {
        return db.jdbc().queryForMap(
                "SELECT " + column + " FROM contract_flow_node WHERE flow_id=? AND node_key=?",
                flowId, nodeKey).get(column);
    }

    private String withdrawState(Long withdrawId) {
        return db.jdbc().queryForObject(
                "SELECT state FROM contract_flow_withdraw WHERE id=?", String.class, withdrawId);
    }

    private int countNodes(Long flowId) {
        return db.jdbc().queryForObject(
                "SELECT COUNT(*) FROM contract_flow_node WHERE flow_id=?",
                Integer.class, flowId);
    }

    private List<String> nodeKeys(Long flowId) {
        return db.jdbc().queryForList(
                "SELECT node_key FROM contract_flow_node WHERE flow_id=? ORDER BY seq",
                String.class, flowId);
    }

    private int nodeSeq(Long flowId, String nodeKey) {
        return db.jdbc().queryForObject(
                "SELECT seq FROM contract_flow_node WHERE flow_id=? AND node_key=?",
                Integer.class, flowId, nodeKey);
    }

    /** 不变量检查：同一流程内 PENDING 节点数。 */
    private int countPending(Long flowId) {
        return db.jdbc().queryForObject(
                "SELECT COUNT(*) FROM contract_flow_node WHERE flow_id=? AND state=?",
                Integer.class, flowId, NODE_PENDING);
    }

    private int countEvents(Long flowId, String type) {
        return db.jdbc().queryForObject(
                "SELECT COUNT(*) FROM contract_flow_event WHERE flow_id=? AND event_type=?",
                Integer.class, flowId, type);
    }

    private int countEventsByRef(Long flowId, String type, Long refId) {
        return db.jdbc().queryForObject("""
                SELECT COUNT(*) FROM contract_flow_event
                WHERE flow_id=? AND event_type=? AND ref_id=?
                """, Integer.class, flowId, type, refId);
    }

    /** 要素/日程确认事件挂在上传人节点上（node_id 必须非空，design v0.4 §1.3）。 */
    private void confirm(Long flowId, String type, Long userId) {
        db.jdbc().update("""
                INSERT INTO contract_flow_event(flow_id,node_id,event_type,actor_id,actor_type)
                VALUES(?,?,?,?,'USER')
                """, flowId, nodeId(flowId, NODE_UPLOADER), type, userId);
    }

    private void assertReason(Runnable action, String expectedReason) {
        assertThatThrownBy(action::run)
                .isInstanceOf(ContractFlowException.class)
                .extracting(e -> ((ContractFlowException) e).getReason())
                .isEqualTo(expectedReason);
    }
}
