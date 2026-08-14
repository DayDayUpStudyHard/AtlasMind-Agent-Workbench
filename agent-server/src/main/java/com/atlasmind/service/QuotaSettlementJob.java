package com.atlasmind.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/** Settles quota reservations after the Python runtime writes a terminal run status. */
@Slf4j
@Component
@RequiredArgsConstructor
public class QuotaSettlementJob {

    private final JdbcTemplate jdbc;
    private final QuotaService quotaService;

    @Scheduled(fixedDelayString = "${atlasmind.quota.settlement-interval-ms:5000}")
    public void settleTerminalRuns() {
        List<Map<String, Object>> runs = jdbc.queryForList("""
                SELECT r.id, r.initiated_by, r.status
                FROM agent_run r
                WHERE r.initiated_by IS NOT NULL
                  AND r.status IN ('COMPLETED','FAILED','CANCELLED','LIMITED')
                  AND EXISTS (
                      SELECT 1 FROM quota_transaction q
                      WHERE q.run_id=r.id AND q.type='RESERVE'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM quota_transaction q
                      WHERE q.run_id=r.id AND q.type IN ('CONFIRM','REFUND')
                  )
                ORDER BY r.id
                LIMIT 100
                """);

        for (Map<String, Object> run : runs) {
            Long runId = ((Number) run.get("id")).longValue();
            Long userId = ((Number) run.get("initiated_by")).longValue();
            String status = String.valueOf(run.get("status"));
            try {
                // LIMITED runs consumed real quota and delivered a scoped
                // report — confirm, never refund (the §6.4 diagnostics record
                // what the scope cut, not a failed execution).
                if ("COMPLETED".equals(status) || "LIMITED".equals(status)) {
                    quotaService.confirm(userId, runId);
                } else {
                    quotaService.refund(userId, runId);
                }
            } catch (Exception exception) {
                log.warn("Quota settlement failed for run {}: {}", runId, exception.getMessage());
            }
        }
    }
}
