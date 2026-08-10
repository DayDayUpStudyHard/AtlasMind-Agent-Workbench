package com.atlasmind.service;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;
import java.util.Set;

/**
 * 合同分析额度服务 — 两阶段预扣机制。
 * <p>
 * reserve → 发起 Agent Run 时预扣 1 次额度（reserved+1）
 * confirm → Run 成功时确认消耗（reserved-1, used+1）
 * refund  → Run 失败时退还（reserved-1）
 * adjust  → 管理员调整总额
 * <p>
 * 所有状态变更均使用 SELECT FOR UPDATE 保证并发安全。
 */
@Service
@RequiredArgsConstructor
public class QuotaService {

    private final JdbcTemplate jdbc;

    /**
     * 预扣：开始 Agent Run 时调用。幂等：同一 runId 多次调用只生效一次。
     * @throws QuotaExceededException 额度不足
     */
    @Transactional
    public void reserve(Long userId, Long runId) {
        String idempotencyKey = "run:" + runId + ":RESERVE";

        lockAndValidateRun(userId, runId, Set.of(
                "CREATED", "CONTEXT_BUILDING", "PLANNING", "ANALYZING",
                "VERIFYING", "WAITING_HUMAN", "WAITING_APPROVAL"));

        var rows = jdbc.queryForList(
            "SELECT total_quota, used_count, reserved_count FROM user_quota WHERE user_id=? FOR UPDATE",
            userId);
        if (rows.isEmpty()) throw new IllegalStateException("用户无额度记录，请联系管理员分配额度");

        if (hasIdempotencyKey(idempotencyKey)) return;

        var row = rows.get(0);
        int total = ((Number) row.get("total_quota")).intValue();
        int used = ((Number) row.get("used_count")).intValue();
        int reserved = ((Number) row.get("reserved_count")).intValue();
        int available = total - used - reserved;
        if (available <= 0) throw new QuotaExceededException("合同分析额度已用完");

        jdbc.update(
            "UPDATE user_quota SET reserved_count = reserved_count + 1 WHERE user_id=?",
            userId);

        int balanceAfter = total - used - (reserved + 1);
        jdbc.update("""
            INSERT INTO quota_transaction (user_id, amount, type, balance_after, run_id, idempotency_key)
            VALUES (?, -1, 'RESERVE', ?, ?, ?)
            """, userId, balanceAfter, runId, idempotencyKey);
    }

    /**
     * 确认：Agent Run 成功后调用。幂等：同一 runId 多次 confirm 只生效一次。
     */
    @Transactional
    public void confirm(Long userId, Long runId) {
        String idempotencyKey = "run:" + runId + ":CONFIRM";

        lockAndValidateRun(userId, runId, Set.of("COMPLETED"));

        var quotaRows = jdbc.queryForList(
            "SELECT reserved_count FROM user_quota WHERE user_id=? FOR UPDATE", userId);
        if (quotaRows.isEmpty()) throw new IllegalStateException("用户无额度记录");

        if (hasSettlement(runId)) return;
        requireReservation(userId, runId);
        int reservedCount = ((Number) quotaRows.get(0).get("reserved_count")).intValue();
        if (reservedCount <= 0) throw new IllegalStateException("额度预扣状态不一致");

        jdbc.update(
            "UPDATE user_quota SET reserved_count = reserved_count - 1, used_count = used_count + 1 WHERE user_id=?",
            userId);

        var updated = jdbc.queryForList(
            "SELECT total_quota, used_count, reserved_count FROM user_quota WHERE user_id=?", userId);
        if (!updated.isEmpty()) {
            var row = updated.get(0);
            int total = ((Number) row.get("total_quota")).intValue();
            int used = ((Number) row.get("used_count")).intValue();
            int reserved = ((Number) row.get("reserved_count")).intValue();
            jdbc.update("""
                INSERT INTO quota_transaction (user_id, amount, type, balance_after, run_id, idempotency_key)
                VALUES (?, 0, 'CONFIRM', ?, ?, ?)
                """, userId, total - used - reserved, runId, idempotencyKey);
        }
    }

    /**
     * 退还：Agent Run 失败后调用。幂等：同一 runId 多次 refund 只生效一次。
     */
    @Transactional
    public void refund(Long userId, Long runId) {
        String idempotencyKey = "run:" + runId + ":REFUND";

        lockAndValidateRun(userId, runId, Set.of("FAILED", "CANCELLED"));

        var quotaRows = jdbc.queryForList(
            "SELECT reserved_count FROM user_quota WHERE user_id=? FOR UPDATE", userId);
        if (quotaRows.isEmpty()) throw new IllegalStateException("用户无额度记录");

        if (hasSettlement(runId)) return;
        requireReservation(userId, runId);
        int reservedCount = ((Number) quotaRows.get(0).get("reserved_count")).intValue();
        if (reservedCount <= 0) throw new IllegalStateException("额度预扣状态不一致");

        jdbc.update(
            "UPDATE user_quota SET reserved_count = reserved_count - 1 WHERE user_id=?",
            userId);

        var updated = jdbc.queryForList(
            "SELECT total_quota, used_count, reserved_count FROM user_quota WHERE user_id=?", userId);
        if (!updated.isEmpty()) {
            var row = updated.get(0);
            int total = ((Number) row.get("total_quota")).intValue();
            int used = ((Number) row.get("used_count")).intValue();
            int reserved = ((Number) row.get("reserved_count")).intValue();
            jdbc.update("""
                INSERT INTO quota_transaction (user_id, amount, type, balance_after, run_id, idempotency_key)
                VALUES (?, 1, 'REFUND', ?, ?, ?)
                """, userId, total - used - reserved, runId, idempotencyKey);
        }
    }

    /**
     * 管理员调整额度（正数为增加，负数为扣减）。
     */
    @Transactional
    public void adjust(Long userId, int delta, Long operatorId, String remark) {
        var rows = jdbc.queryForList(
            "SELECT total_quota, used_count, reserved_count FROM user_quota WHERE user_id=? FOR UPDATE", userId);
        if (rows.isEmpty()) throw new IllegalArgumentException("用户无额度记录");

        var row = rows.get(0);
        int total = ((Number) row.get("total_quota")).intValue();
        int used = ((Number) row.get("used_count")).intValue();
        int reserved = ((Number) row.get("reserved_count")).intValue();
        if (total + delta < used + reserved) {
            throw new IllegalArgumentException("不能扣减到低于已用量和预扣量之和");
        }

        jdbc.update("UPDATE user_quota SET total_quota = total_quota + ? WHERE user_id=?", delta, userId);

        var updated = jdbc.queryForList(
            "SELECT total_quota, used_count, reserved_count FROM user_quota WHERE user_id=?", userId);
        if (!updated.isEmpty()) {
            var updatedRow = updated.get(0);
            jdbc.update("""
                INSERT INTO quota_transaction (user_id, amount, type, balance_after, operator_id, remark)
                VALUES (?, ?, 'ADMIN_ADJUST', ?, ?, ?)
                """, userId, delta,
                ((Number) updatedRow.get("total_quota")).intValue()
                    - ((Number) updatedRow.get("used_count")).intValue()
                    - ((Number) updatedRow.get("reserved_count")).intValue(),
                operatorId, remark);
        }
    }

    /** Check if a user has available quota. */
    public boolean hasQuota(Long userId) {
        var rows = jdbc.queryForList(
            "SELECT total_quota, used_count, reserved_count FROM user_quota WHERE user_id=?", userId);
        if (rows.isEmpty()) return false;
        var row = rows.get(0);
        int total = ((Number) row.get("total_quota")).intValue();
        int used = ((Number) row.get("used_count")).intValue();
        int reserved = ((Number) row.get("reserved_count")).intValue();
        return total - used - reserved > 0;
    }

    /** Get quota info for display. */
    public Map<String, Object> getQuota(Long userId) {
        var rows = jdbc.queryForList(
            "SELECT total_quota, used_count, reserved_count FROM user_quota WHERE user_id=?", userId);
        if (rows.isEmpty()) return Map.of("totalQuota", 0, "usedCount", 0, "reservedCount", 0, "available", 0);
        var row = rows.get(0);
        int total = ((Number) row.get("total_quota")).intValue();
        int used = ((Number) row.get("used_count")).intValue();
        int reserved = ((Number) row.get("reserved_count")).intValue();
        return Map.of("totalQuota", total, "usedCount", used, "reservedCount", reserved,
                "available", total - used - reserved);
    }

    /** Ensure a user has a quota row (called at user creation). */
    public void ensureQuotaRow(Long userId, int initialTotal) {
        jdbc.update("""
            INSERT IGNORE INTO user_quota (user_id, total_quota) VALUES (?, ?)
            """, userId, initialTotal);
    }

    private boolean hasIdempotencyKey(String idempotencyKey) {
        Integer existing = jdbc.queryForObject(
            "SELECT COUNT(*) FROM quota_transaction WHERE idempotency_key=?",
            Integer.class,
            idempotencyKey);
        return existing != null && existing > 0;
    }

    private void lockAndValidateRun(Long userId, Long runId, Set<String> allowedStatuses) {
        var runs = jdbc.queryForList(
                "SELECT initiated_by, status FROM agent_run WHERE id=? FOR UPDATE", runId);
        if (runs.isEmpty()) throw new IllegalArgumentException("Agent Run 不存在");
        var run = runs.get(0);
        Long initiatedBy = run.get("initiated_by") instanceof Number n ? n.longValue() : null;
        if (!userId.equals(initiatedBy)) throw new IllegalStateException("额度用户与 Run 发起人不一致");
        String status = String.valueOf(run.get("status"));
        if (!allowedStatuses.contains(status)) {
            throw new IllegalStateException("Run 状态不允许额度变更: " + status);
        }
    }

    private void requireReservation(Long userId, Long runId) {
        Integer reserved = jdbc.queryForObject("""
                SELECT COUNT(*) FROM quota_transaction
                WHERE user_id=? AND run_id=? AND type='RESERVE'
                """, Integer.class, userId, runId);
        if (reserved == null || reserved == 0) {
            throw new IllegalStateException("Run 没有对应的额度预扣记录");
        }
    }

    private boolean hasSettlement(Long runId) {
        Integer settled = jdbc.queryForObject("""
                SELECT COUNT(*) FROM quota_transaction
                WHERE run_id=? AND type IN ('CONFIRM','REFUND')
                """, Integer.class, runId);
        return settled != null && settled > 0;
    }

    /** Exception thrown when quota is exhausted. */
    public static class QuotaExceededException extends RuntimeException {
        public QuotaExceededException(String message) { super(message); }
    }
}
