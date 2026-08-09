package com.atlasmind.service;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;

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
            ON DUPLICATE KEY UPDATE amount=VALUES(amount)
            """, userId, balanceAfter, runId, idempotencyKey);
    }

    /**
     * 确认：Agent Run 成功后调用。幂等：同一 runId 多次 confirm 只生效一次。
     */
    @Transactional
    public void confirm(Long userId, Long runId) {
        String idempotencyKey = "run:" + runId + ":CONFIRM";

        jdbc.queryForList(
            "SELECT reserved_count FROM user_quota WHERE user_id=? FOR UPDATE", userId);

        if (hasIdempotencyKey(idempotencyKey)) return;

        jdbc.update(
            "UPDATE user_quota SET reserved_count = GREATEST(reserved_count - 1, 0), used_count = used_count + 1 WHERE user_id=?",
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
                ON DUPLICATE KEY UPDATE amount=VALUES(amount)
                """, userId, total - used - reserved, runId, idempotencyKey);
        }
    }

    /**
     * 退还：Agent Run 失败后调用。幂等：同一 runId 多次 refund 只生效一次。
     */
    @Transactional
    public void refund(Long userId, Long runId) {
        String idempotencyKey = "run:" + runId + ":REFUND";

        jdbc.queryForList(
            "SELECT reserved_count FROM user_quota WHERE user_id=? FOR UPDATE", userId);

        if (hasIdempotencyKey(idempotencyKey)) return;

        jdbc.update(
            "UPDATE user_quota SET reserved_count = GREATEST(reserved_count - 1, 0) WHERE user_id=?",
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
                ON DUPLICATE KEY UPDATE amount=VALUES(amount)
                """, userId, total - used - reserved, runId, idempotencyKey);
        }
    }

    /**
     * 管理员调整额度（正数为增加，负数为扣减）。
     */
    @Transactional
    public void adjust(Long userId, int delta, Long operatorId, String remark) {
        var rows = jdbc.queryForList(
            "SELECT total_quota, used_count FROM user_quota WHERE user_id=? FOR UPDATE", userId);
        if (rows.isEmpty()) throw new IllegalArgumentException("用户无额度记录");

        var row = rows.get(0);
        int total = ((Number) row.get("total_quota")).intValue();
        int used = ((Number) row.get("used_count")).intValue();
        if (total + delta < used) {
            throw new IllegalArgumentException("不能扣减到低于已用量");
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

    /** Exception thrown when quota is exhausted. */
    public static class QuotaExceededException extends RuntimeException {
        public QuotaExceededException(String message) { super(message); }
    }
}
