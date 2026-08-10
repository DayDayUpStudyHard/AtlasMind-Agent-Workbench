package com.atlasmind.service;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;

/**
 * 合同协作成员服务 — 管理 contract_member 表。
 *
 * <p>角色层级：OWNER > EDITOR > REVIEWER > VIEWER
 * <p>权限规则：
 * <ul>
 *   <li>OWNER — 可管理成员、读写合同、审核内容、转移所有权</li>
 *   <li>EDITOR — 可读写合同、审核内容，不可管理成员</li>
 *   <li>REVIEWER — 可读合同、审核内容，不可写</li>
 *   <li>VIEWER — 只读</li>
 * </ul>
 * <p>安全约束：
 * <ul>
 *   <li>不能移除最后一个 OWNER</li>
 *   <li>只有 OWNER 可以转移所有权</li>
 *   <li>非成员（visibility fallback 用户）无成员角色</li>
 * </ul>
 */
@Service
@RequiredArgsConstructor
public class ContractMemberService {

    private final JdbcTemplate jdbc;

    // ── Queries ────────────────────────────────────────────────────

    /** 列出合同的所有活跃成员（含用户信息）。 */
    public List<Map<String, Object>> listMembers(Long caseId) {
        return jdbc.queryForList("""
                SELECT m.id, m.case_id AS caseId, m.user_id AS userId,
                       u.username, u.nickname, u.avatar,
                       m.role, m.status,
                       m.invited_by AS invitedBy,
                       m.joined_at AS joinedAt,
                       m.create_time AS createTime
                FROM contract_member m
                JOIN t_user u ON u.id = m.user_id
                WHERE m.case_id = ? AND m.status = 'ACTIVE'
                ORDER BY CASE m.role WHEN 'OWNER' THEN 1 WHEN 'EDITOR' THEN 2 WHEN 'REVIEWER' THEN 3 ELSE 4 END, m.create_time
                """, caseId);
    }

    /** 获取用户在合同中的角色；非成员返回 null。 */
    public String getMemberRole(Long caseId, Long userId) {
        var rows = jdbc.queryForList(
                "SELECT role FROM contract_member WHERE case_id=? AND user_id=? AND status='ACTIVE'",
                caseId, userId);
        return rows.isEmpty() ? null : String.valueOf(rows.get(0).get("role"));
    }

    /** 用户是否为任何角色的活跃成员。 */
    public boolean isMember(Long caseId, Long userId) {
        Integer count = jdbc.queryForObject(
                "SELECT COUNT(*) FROM contract_member WHERE case_id=? AND user_id=? AND status='ACTIVE'",
                Integer.class, caseId, userId);
        return count != null && count > 0;
    }

    // ── Permissions ────────────────────────────────────────────────

    public boolean canWrite(Long caseId, Long userId) {
        String role = getMemberRole(caseId, userId);
        return "OWNER".equals(role) || "EDITOR".equals(role);
    }

    public boolean canReview(Long caseId, Long userId) {
        String role = getMemberRole(caseId, userId);
        return "OWNER".equals(role) || "EDITOR".equals(role) || "REVIEWER".equals(role);
    }

    public boolean canManageMembers(Long caseId, Long userId) {
        return "OWNER".equals(getMemberRole(caseId, userId));
    }

    // ── Mutations ──────────────────────────────────────────────────

    /** 创建合同时自动添加创建者为 OWNER。幂等 — 如果已存在则不重复添加。 */
    @Transactional
    public void addOwner(Long caseId, Long userId) {
        var existing = jdbc.queryForList(
                "SELECT id, role, status FROM contract_member WHERE case_id=? AND user_id=?",
                caseId, userId);
        if (!existing.isEmpty()) {
            var row = existing.get(0);
            String role = String.valueOf(row.get("role"));
            String status = String.valueOf(row.get("status"));
            if ("ACTIVE".equals(status) && "OWNER".equals(role)) return;
            // 已存在但非 OWNER 或非 ACTIVE — 提升为 OWNER
            jdbc.update("UPDATE contract_member SET role='OWNER', status='ACTIVE', removed_at=NULL, update_time=NOW() WHERE id=?",
                    row.get("id"));
            return;
        }
        jdbc.update("INSERT INTO contract_member (case_id, user_id, role, status, joined_at) VALUES (?,?,'OWNER','ACTIVE',NOW())",
                caseId, userId);
    }

    /** 邀请成员（需要 OWNER 权限，由调用方校验）。role 不能为 OWNER。 */
    @Transactional
    public void inviteMember(Long caseId, Long invitedUserId, String role, Long invitedBy) {
        if ("OWNER".equals(role)) {
            throw new IllegalArgumentException("不能通过邀请添加 OWNER；请使用转移所有权功能");
        }
        if (!List.of("EDITOR", "REVIEWER", "VIEWER").contains(role)) {
            throw new IllegalArgumentException("无效的角色: " + role);
        }
        // 幂等：已存在则更新
        int updated = jdbc.update(
                "UPDATE contract_member SET role=?, status='ACTIVE', invited_by=?, joined_at=NOW(), removed_at=NULL, update_time=NOW() WHERE case_id=? AND user_id=?",
                role, invitedBy, caseId, invitedUserId);
        if (updated == 0) {
            jdbc.update("INSERT INTO contract_member (case_id, user_id, role, status, invited_by, joined_at) VALUES (?,?,?,'ACTIVE',?,NOW())",
                    caseId, invitedUserId, role, invitedBy);
        }
    }

    /** 更新成员角色。OWNER 可改任何人；EDITOR 只能降级同级及以下。 */
    @Transactional
    public void updateMemberRole(Long caseId, Long userId, String newRole, Long operatedBy) {
        String operatorRole = getMemberRole(caseId, operatedBy);
        if (operatorRole == null) throw new IllegalArgumentException("您不是该合同成员");

        String targetRole = getMemberRole(caseId, userId);
        if (targetRole == null) throw new IllegalArgumentException("目标用户不是该合同成员");

        if (!List.of("OWNER", "EDITOR", "REVIEWER", "VIEWER").contains(newRole)) {
            throw new IllegalArgumentException("无效的角色: " + newRole);
        }

        // 不能通过此方法转移/剥夺 OWNER；OWNER 转移由 transferOwnership 处理
        if ("OWNER".equals(newRole)) {
            throw new IllegalArgumentException("请使用转移所有权功能来设置 OWNER");
        }
        if ("OWNER".equals(targetRole) && !"OWNER".equals(operatorRole)) {
            throw new IllegalArgumentException("只有 OWNER 可以更改 OWNER 的角色");
        }

        if ("EDITOR".equals(operatorRole)) {
            // EDITOR 只能改 VIEWER 和 REVIEWER
            if ("EDITOR".equals(targetRole) || "OWNER".equals(targetRole)) {
                throw new IllegalArgumentException("EDITOR 不能更改同级或上级成员的角色");
            }
        }

        jdbc.update("UPDATE contract_member SET role=?, update_time=NOW() WHERE case_id=? AND user_id=? AND status='ACTIVE'",
                newRole, caseId, userId);
    }

    /** 移除成员。不能移除自己（OWNER 也不能自己退出——请使用转移所有权）。 */
    @Transactional
    public void removeMember(Long caseId, Long userId, Long operatedBy) {
        String targetRole = getMemberRole(caseId, userId);
        if (targetRole == null) throw new IllegalArgumentException("目标用户不是该合同成员");

        // 不能移除最后一个 OWNER
        if ("OWNER".equals(targetRole)) {
            Integer ownerCount = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM contract_member WHERE case_id=? AND role='OWNER' AND status='ACTIVE'",
                    Integer.class, caseId);
            if (ownerCount != null && ownerCount <= 1) {
                throw new IllegalArgumentException("不能移除唯一 OWNER；请先转移所有权");
            }
        }

        jdbc.update("UPDATE contract_member SET status='REMOVED', removed_at=NOW(), update_time=NOW() WHERE case_id=? AND user_id=? AND status='ACTIVE'",
                caseId, userId);
    }

    /** 转移所有权 — 仅当前 OWNER 可操作。使用 SELECT FOR UPDATE 保证原子性。 */
    @Transactional
    public void transferOwnership(Long caseId, Long newOwnerId, Long currentOwnerId) {
        if (newOwnerId.equals(currentOwnerId)) {
            throw new IllegalArgumentException("不能将所有权转移给自己");
        }

        // 锁定当前 OWNER 记录
        var currentOwners = jdbc.queryForList(
                "SELECT id FROM contract_member WHERE case_id=? AND user_id=? AND role='OWNER' AND status='ACTIVE' FOR UPDATE",
                caseId, currentOwnerId);
        if (currentOwners.isEmpty()) {
            throw new IllegalArgumentException("只有当前 OWNER 可以转移所有权");
        }

        // 锁定新 OWNER 记录或确认不存在
        var newMembers = jdbc.queryForList(
                "SELECT id, role, status FROM contract_member WHERE case_id=? AND user_id=? FOR UPDATE",
                caseId, newOwnerId);

        if (newMembers.isEmpty()) {
            // 新 OWNER 还不是成员 — 直接插入为 OWNER
            jdbc.update("INSERT INTO contract_member (case_id, user_id, role, status, joined_at) VALUES (?,?,'OWNER','ACTIVE',NOW())",
                    caseId, newOwnerId);
        } else {
            // 已是成员 — 升级为 OWNER
            jdbc.update("UPDATE contract_member SET role='OWNER', status='ACTIVE', removed_at=NULL, update_time=NOW() WHERE case_id=? AND user_id=?",
                    caseId, newOwnerId);
        }

        // 将当前 OWNER 降级为 EDITOR（保留在合同中）
        jdbc.update("UPDATE contract_member SET role='EDITOR', update_time=NOW() WHERE case_id=? AND user_id=? AND role='OWNER'",
                caseId, currentOwnerId);

        // 同步回写 contract_case.owner_id / maintainer_id
        jdbc.update("UPDATE contract_case SET owner_id=?, maintainer_id=? WHERE id=?",
                newOwnerId, newOwnerId, caseId);
    }

    /**
     * ADMIN 强制设定 OWNER — 绕过 "当前必须是 OWNER" 的校验。
     * 用于原 OWNER 离职/误操作后 ADMIN 接管恢复。
     * <p>先清掉所有已有 OWNER（降为 EDITOR），再将目标用户设为 OWNER。
     */
    @Transactional
    public void forceSetOwner(Long caseId, Long newOwnerId) {
        // 将所有现有 OWNER 降级为 EDITOR
        jdbc.update("UPDATE contract_member SET role='EDITOR', update_time=NOW() WHERE case_id=? AND role='OWNER' AND status='ACTIVE'",
                caseId);

        // 将目标用户设为 OWNER
        var existing = jdbc.queryForList(
                "SELECT id FROM contract_member WHERE case_id=? AND user_id=? FOR UPDATE",
                caseId, newOwnerId);
        if (existing.isEmpty()) {
            jdbc.update("INSERT INTO contract_member (case_id, user_id, role, status, joined_at) VALUES (?,?,'OWNER','ACTIVE',NOW())",
                    caseId, newOwnerId);
        } else {
            jdbc.update("UPDATE contract_member SET role='OWNER', status='ACTIVE', removed_at=NULL, update_time=NOW() WHERE case_id=? AND user_id=?",
                    caseId, newOwnerId);
        }

        // 同步回写 contract_case.owner_id / maintainer_id
        jdbc.update("UPDATE contract_case SET owner_id=?, maintainer_id=? WHERE id=?",
                newOwnerId, newOwnerId, caseId);
    }
}
