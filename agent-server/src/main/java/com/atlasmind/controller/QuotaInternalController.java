package com.atlasmind.controller;

import com.atlasmind.common.Result;
import com.atlasmind.service.QuotaService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

/**
 * 内部额度结算端点 — 供 Python Agent Runtime 在 Run 终态时回调。
 * <p>
 * 鉴权：检查 X-Internal-Token 请求头，与 atlasmind.internal-token 配置比对。
 * QuotaSettlementJob 作为兜底，此端点用于消除结算延迟窗口。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/internal/quota")
public class QuotaInternalController {

    private final QuotaService quotaService;
    private final JdbcTemplate jdbc;

    @Value("${atlasmind.internal-token:}")
    private String internalToken;

    @ModelAttribute
    private void checkInternalAuth(HttpServletRequest request) {
        if (internalToken == null || internalToken.isBlank()) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR,
                    "Internal token not configured on server");
        }
        String provided = request.getHeader("X-Internal-Token");
        if (!internalToken.equals(provided)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        }
    }

    @PostMapping("/confirm/{runId}")
    public Result<?> confirm(@PathVariable Long runId) {
        var runs = jdbc.queryForList(
                "SELECT initiated_by, status FROM agent_run WHERE id=?", runId);
        if (runs.isEmpty()) return Result.fail("Run not found: " + runId);

        var run = runs.get(0);
        String status = String.valueOf(run.get("status"));
        if (!"COMPLETED".equals(status)) {
            return Result.fail("Run " + runId + " is not COMPLETED (current: " + status + ")");
        }

        Object initiatedBy = run.get("initiated_by");
        if (!(initiatedBy instanceof Number)) {
            return Result.fail("Run " + runId + " has no initiated_by user");
        }

        Long userId = ((Number) initiatedBy).longValue();
        quotaService.confirm(userId, runId);
        return Result.ok(Map.of("settled", true, "runId", runId, "action", "CONFIRM"));
    }

    @PostMapping("/refund/{runId}")
    public Result<?> refund(@PathVariable Long runId) {
        var runs = jdbc.queryForList(
                "SELECT initiated_by, status FROM agent_run WHERE id=?", runId);
        if (runs.isEmpty()) return Result.fail("Run not found: " + runId);

        var run = runs.get(0);
        String status = String.valueOf(run.get("status"));
        if (!"FAILED".equals(status) && !"CANCELLED".equals(status)) {
            return Result.fail("Run " + runId + " is not FAILED/CANCELLED (current: " + status + ")");
        }

        Object initiatedBy = run.get("initiated_by");
        if (!(initiatedBy instanceof Number)) {
            return Result.fail("Run " + runId + " has no initiated_by user");
        }

        Long userId = ((Number) initiatedBy).longValue();
        quotaService.refund(userId, runId);
        return Result.ok(Map.of("settled", true, "runId", runId, "action", "REFUND"));
    }
}
