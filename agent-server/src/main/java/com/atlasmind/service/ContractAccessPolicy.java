package com.atlasmind.service;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.entity.User;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

/**
 * 统一合同访问策略 — 所有合同资源读写的安全入口。
 * <p>
 * ADMIN 全局通行；USER 按 visibility 模式过滤：
 * <ul>
 *   <li>{@code ALL} — 全公司可见，所有用户可访问</li>
 *   <li>{@code LEGACY_REVIEW} — 过渡期等价于 ALL</li>
 *   <li>{@code DEPARTMENT} — 仅同部门用户可访问</li>
 *   <li>{@code SPECIFIED} — 仅 contract_department_visibility 表中指定的部门可访问</li>
 * </ul>
 * 不可见的合同始终返回 404 以隐藏其存在。
 */
@Component
@RequiredArgsConstructor
public class ContractAccessPolicy {

    private final JdbcTemplate jdbc;
    private final UserService userService;

    /**
     * 检查当前用户是否可以访问指定合同。
     * @throws RuntimeException 如果不可访问（始终返回 404 语义）
     */
    public void checkAccess(Long caseId) {
        long userId = StpUtil.getLoginIdAsLong();
        if (isAdmin(userId)) return;

        var contracts = jdbc.queryForList(
            "SELECT id, visibility, department_id FROM contract_case WHERE id=? AND deleted=0",
            caseId);
        if (contracts.isEmpty()) throw notFound("合同不存在");

        var contract = contracts.get(0);
        String visibility = (String) contract.getOrDefault("visibility", "ALL");
        Long contractDeptId = toLongOrNull(contract.get("department_id"));
        Long userDeptId = getCurrentUserDepartmentId(userId);

        if ("ALL".equals(visibility) || "LEGACY_REVIEW".equals(visibility)) return;
        if ("DEPARTMENT".equals(visibility)) {
            if (contractDeptId != null && contractDeptId.equals(userDeptId)) return;
        }
        if ("SPECIFIED".equals(visibility)) {
            if (userDeptId != null) {
                Integer count = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM contract_department_visibility " +
                    "WHERE contract_id=? AND department_id=?",
                    Integer.class, caseId, userDeptId);
                if (count != null && count > 0) return;
            }
        }
        throw notFound("合同不存在");
    }

    /**
     * 构建前台合同查询的可见性 WHERE 子句。
     * @return SQL 片段（可能为空字符串，表示无限制），参数追加到 params
     */
    public String buildVisibilityFilter(List<Object> params) {
        long userId = StpUtil.getLoginIdAsLong();
        if (isAdmin(userId)) return "";

        Long userDeptId = getCurrentUserDepartmentId(userId);
        params.add(userDeptId);
        params.add(userDeptId);
        return """
            AND (
              c.visibility IN ('ALL','LEGACY_REVIEW')
              OR (c.visibility = 'DEPARTMENT' AND c.department_id = ?)
              OR (c.visibility = 'SPECIFIED'
                  AND EXISTS (SELECT 1 FROM contract_department_visibility cdv
                              WHERE cdv.contract_id = c.id AND cdv.department_id = ?))
            )
            """;
    }

    /** Build visibility filter for queries where the table alias is absent (direct FROM contract_case). */
    public String buildVisibilityFilterNoAlias(List<Object> params) {
        long userId = StpUtil.getLoginIdAsLong();
        if (isAdmin(userId)) return "";

        Long userDeptId = getCurrentUserDepartmentId(userId);
        params.add(userDeptId);
        params.add(userDeptId);
        return """
            AND (
              visibility IN ('ALL','LEGACY_REVIEW')
              OR (visibility = 'DEPARTMENT' AND department_id = ?)
              OR (visibility = 'SPECIFIED'
                  AND EXISTS (SELECT 1 FROM contract_department_visibility cdv
                              WHERE cdv.contract_id = id AND cdv.department_id = ?))
            )
            """;
    }

    public boolean isAdmin(long userId) {
        User user = userService.getById(userId);
        return user != null && "ADMIN".equals(user.getRole());
    }

    private Long getCurrentUserDepartmentId(long userId) {
        User user = userService.getById(userId);
        return user != null ? user.getDepartmentId() : null;
    }

    private ResponseStatusException notFound(String msg) {
        return new ResponseStatusException(HttpStatus.NOT_FOUND, msg);
    }

    private Long toLongOrNull(Object val) {
        if (val instanceof Number n) return n.longValue();
        if (val instanceof String s && !s.isBlank()) {
            try { return Long.parseLong(s); } catch (NumberFormatException e) { return null; }
        }
        return null;
    }
}
