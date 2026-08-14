package com.atlasmind.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.JdbcTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@JdbcTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:quota;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1"
})
@Import(QuotaService.class)
class QuotaServiceTest {

    @Autowired
    private JdbcTemplate jdbc;

    @Autowired
    private QuotaService quotaService;

    @BeforeEach
    void setUp() {
        jdbc.execute("DROP TABLE IF EXISTS quota_transaction");
        jdbc.execute("DROP TABLE IF EXISTS user_quota");
        jdbc.execute("DROP TABLE IF EXISTS agent_run");
        jdbc.execute("""
                CREATE TABLE agent_run (
                    id BIGINT PRIMARY KEY,
                    initiated_by BIGINT,
                    status VARCHAR(32) NOT NULL
                )
                """);
        jdbc.execute("""
                CREATE TABLE user_quota (
                    user_id BIGINT PRIMARY KEY,
                    total_quota INT NOT NULL,
                    used_count INT NOT NULL DEFAULT 0,
                    reserved_count INT NOT NULL DEFAULT 0
                )
                """);
        jdbc.execute("""
                CREATE TABLE quota_transaction (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount INT NOT NULL,
                    type VARCHAR(32) NOT NULL,
                    balance_after INT NOT NULL,
                    operator_id BIGINT,
                    run_id BIGINT,
                    remark VARCHAR(500) DEFAULT '',
                    idempotency_key VARCHAR(128),
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (idempotency_key)
                )
                """);
        jdbc.update("INSERT INTO user_quota (user_id,total_quota) VALUES (1,3)");
    }

    @Test
    void completedRunConsumesReservedQuotaExactlyOnce() {
        createRun(10L, 1L, "CREATED");
        quotaService.reserve(1L, 10L);
        jdbc.update("UPDATE agent_run SET status='COMPLETED' WHERE id=10");

        quotaService.confirm(1L, 10L);
        quotaService.confirm(1L, 10L);

        assertQuota(1, 0);
        assertThat(transactionCount(10L, "CONFIRM")).isEqualTo(1);
    }

    @Test
    void limitedRunConsumesReservedQuotaExactlyOnce() {
        // LIMITED runs delivered a scoped report — real quota consumed,
        // confirm (never refund) so the scheduled settlement job releases
        // the reservation instead of failing on every pass.
        createRun(20L, 1L, "CREATED");
        quotaService.reserve(1L, 20L);
        jdbc.update("UPDATE agent_run SET status='LIMITED' WHERE id=20");

        quotaService.confirm(1L, 20L);
        quotaService.confirm(1L, 20L);

        assertQuota(1, 0);
        assertThat(transactionCount(20L, "CONFIRM")).isEqualTo(1);
    }

    @Test
    void failedRunRefundsReservedQuotaExactlyOnce() {
        createRun(11L, 1L, "CREATED");
        quotaService.reserve(1L, 11L);
        jdbc.update("UPDATE agent_run SET status='FAILED' WHERE id=11");

        quotaService.refund(1L, 11L);
        quotaService.refund(1L, 11L);

        assertQuota(0, 0);
        assertThat(transactionCount(11L, "REFUND")).isEqualTo(1);
    }

    @Test
    void settlementWithoutReservationIsRejected() {
        createRun(12L, 1L, "COMPLETED");

        assertThatThrownBy(() -> quotaService.confirm(1L, 12L))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("预扣");
    }

    @Test
    void quotaCannotBeSettledAgainstAnotherUser() {
        createRun(13L, 2L, "COMPLETED");

        assertThatThrownBy(() -> quotaService.confirm(1L, 13L))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("发起人");
    }

    private void createRun(long runId, long userId, String status) {
        jdbc.update("INSERT INTO agent_run (id,initiated_by,status) VALUES (?,?,?)", runId, userId, status);
    }

    private void assertQuota(int used, int reserved) {
        var row = jdbc.queryForMap(
                "SELECT used_count, reserved_count FROM user_quota WHERE user_id=1");
        assertThat(((Number) row.get("used_count")).intValue()).isEqualTo(used);
        assertThat(((Number) row.get("reserved_count")).intValue()).isEqualTo(reserved);
    }

    private int transactionCount(long runId, String type) {
        Integer count = jdbc.queryForObject(
                "SELECT COUNT(*) FROM quota_transaction WHERE run_id=? AND type=?",
                Integer.class, runId, type);
        return count == null ? 0 : count;
    }
}
