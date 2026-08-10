package com.atlasmind.controller.admin;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.service.QuotaService;
import com.atlasmind.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.util.*;

/**
 * 管理员用户管理 API。
 * <pre>
 * GET    /api/admin/users            — 列表（分页、搜索、按角色/部门/状态过滤）
 * POST   /api/admin/users            — 创建（username/password/role/departmentId/quota）
 * GET    /api/admin/users/{id}       — 详情 + 额度
 * PUT    /api/admin/users/{id}       — 编辑（nickname/role/departmentId/status）
 * POST   /api/admin/users/{id}/disable  — 禁用（踢会话+撤 token）
 * POST   /api/admin/users/{id}/enable   — 启用
 * GET    /api/admin/users/{id}/quota/history  — 额度流水
 * POST   /api/admin/users/{id}/quota/adjust   — 调整额度
 * </pre>
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/users")
public class AdminUserController {

    private final JdbcTemplate jdbc;
    private final UserService userService;
    private final QuotaService quotaService;

    @GetMapping
    public Result<Map<String, Object>> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String role,
            @RequestParam(required = false) Long departmentId,
            @RequestParam(required = false) String status) {
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 100));
        int offset = (safePage - 1) * safeSize;

        StringBuilder where = new StringBuilder("WHERE 1=1");
        List<Object> params = new ArrayList<>();

        if (keyword != null && !keyword.isBlank()) {
            where.append(" AND (u.username LIKE ? OR u.nickname LIKE ? OR u.email LIKE ?)");
            String kw = "%" + keyword.trim() + "%";
            params.add(kw); params.add(kw); params.add(kw);
        }
        if (role != null && !role.isBlank()) {
            where.append(" AND u.role=?");
            params.add(role.trim().toUpperCase());
        }
        if (departmentId != null) {
            where.append(" AND u.department_id=?");
            params.add(departmentId);
        }
        if (status != null && !status.isBlank()) {
            where.append(" AND u.status=?");
            params.add(status.trim().toUpperCase());
        }

        List<Object> countParams = new ArrayList<>(params);
        List<Object> listParams = new ArrayList<>(params);
        listParams.add(offset);
        listParams.add(safeSize);

        var records = jdbc.queryForList("""
                SELECT u.id, u.username, u.nickname, u.email, u.role, u.department_id AS departmentId,
                       d.name AS departmentName, u.status, u.create_time AS createTime
                FROM t_user u
                LEFT JOIN department d ON d.id = u.department_id AND d.deleted = 0
                """ + where + " ORDER BY u.id ASC LIMIT ?, ?",
                listParams.toArray());

        Long total = jdbc.queryForObject(
                "SELECT COUNT(*) FROM t_user u " + where, Long.class, countParams.toArray());

        Map<String, Object> result = new HashMap<>();
        result.put("records", records);
        result.put("total", total == null ? 0 : total);
        return Result.ok(result);
    }

    @PostMapping
    @Transactional
    @OperationLog(value = "创建用户", type = "CREATE")
    public Result<Map<String, Object>> create(@RequestBody Map<String, Object> body) {
        String username = str(body, "username");
        String password = str(body, "password");
        if (username.isBlank() || password.isBlank()) throw new IllegalArgumentException("用户名和密码不能为空");

        // Check duplicate
        Integer exists = jdbc.queryForObject(
                "SELECT COUNT(*) FROM t_user WHERE username=?", Integer.class, username);
        if (exists != null && exists > 0) throw new IllegalArgumentException("用户名已存在");

        String nickname = str(body, "nickname");
        if (nickname.isBlank()) nickname = username;
        String role = str(body, "role");
        if (role.isBlank()) role = "USER";
        role = normalizeRole(role);
        String email = str(body, "email");
        Long deptId = toLongOrNull(body.get("departmentId"));
        int initialQuota = body.get("initialQuota") instanceof Number n ? n.intValue() : 100;
        if (initialQuota < 0) throw new IllegalArgumentException("初始额度不能为负数");
        validateDepartment(deptId);

        jdbc.update("""
                INSERT INTO t_user (username, password, nickname, email, role, department_id, status, bio, social_links)
                VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', '', '[]')
                """, username, cn.hutool.crypto.digest.BCrypt.hashpw(password),
                nickname, email, role, deptId);

        Long userId = jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);
        quotaService.ensureQuotaRow(userId, initialQuota);

        return Result.ok(Map.of("created", true, "userId", userId));
    }

    @GetMapping("/{id}")
    public Result<Map<String, Object>> detail(@PathVariable Long id) {
        var rows = jdbc.queryForList("""
                SELECT u.id, u.username, u.nickname, u.email, u.role, u.department_id AS departmentId,
                       d.name AS departmentName, u.status, u.bio, u.social_links AS socialLinks,
                       u.create_time AS createTime
                FROM t_user u
                LEFT JOIN department d ON d.id = u.department_id AND d.deleted = 0
                WHERE u.id=?
                """, id);
        if (rows.isEmpty()) throw new IllegalArgumentException("用户不存在");
        var user = new HashMap<>(rows.get(0));
        user.put("quota", quotaService.getQuota(id));
        return Result.ok(user);
    }

    @PutMapping("/{id}")
    @Transactional
    @OperationLog(value = "编辑用户", type = "UPDATE")
    public Result<Map<String, Object>> update(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        if (body.containsKey("status")) {
            throw new IllegalArgumentException("用户状态只能通过启用/禁用接口修改");
        }
        var users = jdbc.queryForList(
                "SELECT role, status FROM t_user WHERE id=? FOR UPDATE", id);
        if (users.isEmpty()) throw new IllegalArgumentException("用户不存在");
        var currentUser = users.get(0);

        // Last admin protection
        String newRole = str(body, "role");
        if (!newRole.isBlank()) {
            newRole = normalizeRole(newRole);
            if ("ADMIN".equals(currentUser.get("role"))
                    && "ACTIVE".equals(currentUser.get("status"))
                    && !"ADMIN".equals(newRole)
                    && lockActiveAdminIds().size() <= 1) {
                throw new IllegalStateException("不能降级最后一个管理员");
            }
        }

        List<String> sets = new ArrayList<>();
        List<Object> params = new ArrayList<>();
        if (!newRole.isBlank()) { sets.add("role=?"); params.add(newRole.toUpperCase()); }
        if (body.containsKey("departmentId")) {
            Long departmentId = toLongOrNull(body.get("departmentId"));
            validateDepartment(departmentId);
            sets.add("department_id=?"); params.add(departmentId);
        }
        if (body.containsKey("nickname")) { sets.add("nickname=?"); params.add(str(body, "nickname")); }
        if (body.containsKey("email")) { sets.add("email=?"); params.add(str(body, "email")); }
        if (sets.isEmpty()) return Result.ok(Map.of("updated", false));
        params.add(id);
        jdbc.update("UPDATE t_user SET " + String.join(",", sets) + " WHERE id=?", params.toArray());
        return Result.ok(Map.of("updated", true));
    }

    @PostMapping("/{id}/disable")
    @Transactional
    @OperationLog(value = "禁用用户", type = "UPDATE")
    public Result<?> disable(@PathVariable Long id) {
        var users = jdbc.queryForList(
                "SELECT role, status FROM t_user WHERE id=? FOR UPDATE", id);
        if (users.isEmpty()) throw new IllegalArgumentException("用户不存在");
        var user = users.get(0);
        if ("DISABLED".equals(user.get("status"))) {
            return Result.ok(Map.of("disabled", true));
        }
        if ("ADMIN".equals(user.get("role")) && lockActiveAdminIds().size() <= 1) {
            throw new IllegalStateException("不能禁用最后一个管理员");
        }

        jdbc.update("UPDATE t_user SET status='DISABLED' WHERE id=?", id);
        StpUtil.kickout(id);
        userService.revokeAllRefreshTokens(id);
        return Result.ok(Map.of("disabled", true));
    }

    @PostMapping("/{id}/enable")
    @OperationLog(value = "启用用户", type = "UPDATE")
    public Result<?> enable(@PathVariable Long id) {
        jdbc.update("UPDATE t_user SET status='ACTIVE' WHERE id=?", id);
        return Result.ok(Map.of("enabled", true));
    }

    @GetMapping("/{id}/quota/history")
    public Result<List<Map<String, Object>>> quotaHistory(@PathVariable Long id) {
        return Result.ok(jdbc.queryForList("""
                SELECT id, amount, type, balance_after AS balanceAfter,
                       operator_id AS operatorId, run_id AS runId, remark, create_time AS createTime
                FROM quota_transaction WHERE user_id=? ORDER BY id DESC LIMIT 100
                """, id));
    }

    @PostMapping("/{id}/quota/adjust")
    @OperationLog(value = "调整额度", type = "UPDATE")
    public Result<?> adjustQuota(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        int delta = body.get("delta") instanceof Number n ? n.intValue() : 0;
        if (delta == 0) throw new IllegalArgumentException("调整量不能为0");
        String remark = str(body, "remark");
        if (remark.isBlank()) remark = delta > 0 ? "管理员增加额度" : "管理员扣减额度";
        long operatorId = StpUtil.getLoginIdAsLong();
        quotaService.adjust(id, delta, operatorId, remark);
        return Result.ok(Map.of("adjusted", true, "quota", quotaService.getQuota(id)));
    }

    private String str(Map<String, Object> map, String key) {
        Object v = map.get(key);
        return v == null ? "" : v.toString().trim();
    }

    private Long toLongOrNull(Object val) {
        if (val instanceof Number n) return n.longValue();
        if (val instanceof String s && !s.isBlank()) {
            try { return Long.parseLong(s); } catch (NumberFormatException e) { return null; }
        }
        return null;
    }

    private String normalizeRole(String role) {
        String normalized = role == null ? "" : role.trim().toUpperCase(Locale.ROOT);
        if (!Set.of("ADMIN", "USER").contains(normalized)) {
            throw new IllegalArgumentException("角色只能是 ADMIN 或 USER");
        }
        return normalized;
    }

    private void validateDepartment(Long departmentId) {
        if (departmentId == null) return;
        Integer exists = jdbc.queryForObject(
                "SELECT COUNT(*) FROM department WHERE id=? AND deleted=0", Integer.class, departmentId);
        if (exists == null || exists == 0) throw new IllegalArgumentException("部门不存在");
    }

    private List<Long> lockActiveAdminIds() {
        return jdbc.queryForList(
                "SELECT id FROM t_user WHERE role='ADMIN' AND status='ACTIVE' ORDER BY id FOR UPDATE",
                Long.class);
    }
}
