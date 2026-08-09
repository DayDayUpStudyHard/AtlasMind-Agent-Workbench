package com.atlasmind.controller.admin;

import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.util.*;

/**
 * 管理员部门管理 API。
 * <pre>
 * GET    /api/admin/departments            — 列表
 * POST   /api/admin/departments            — 新建
 * PUT    /api/admin/departments/{id}       — 编辑
 * DELETE /api/admin/departments/{id}       — 软删除（is_default=1 拒绝删除）
 * </pre>
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/departments")
public class AdminDepartmentController {

    private final JdbcTemplate jdbc;

    @GetMapping
    public Result<List<Map<String, Object>>> list() {
        return Result.ok(jdbc.queryForList("""
                SELECT id, name, code, is_default AS isDefault, description,
                       deleted, create_time AS createTime, update_time AS updateTime
                FROM department WHERE deleted=0 ORDER BY is_default DESC, id ASC
                """));
    }

    @PostMapping
    @OperationLog(value = "创建部门", type = "CREATE")
    public Result<Map<String, Object>> create(@RequestBody Map<String, Object> body) {
        String name = str(body, "name");
        String code = str(body, "code");
        if (name.isBlank() || code.isBlank()) throw new IllegalArgumentException("部门名称和编码不能为空");

        // Check duplicate
        Integer exists = jdbc.queryForObject(
                "SELECT COUNT(*) FROM department WHERE code=? AND deleted=0", Integer.class, code);
        if (exists != null && exists > 0) throw new IllegalArgumentException("部门编码已存在");

        jdbc.update("""
                INSERT INTO department (name, code, description) VALUES (?,?,?)
                """, name, code, str(body, "description"));

        Long id = jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);
        return Result.ok(Map.of("created", true, "departmentId", id));
    }

    @PutMapping("/{id}")
    @OperationLog(value = "编辑部门", type = "UPDATE")
    public Result<Map<String, Object>> update(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        List<String> sets = new ArrayList<>();
        List<Object> params = new ArrayList<>();
        if (body.containsKey("name")) { sets.add("name=?"); params.add(str(body, "name")); }
        if (body.containsKey("code")) { sets.add("code=?"); params.add(str(body, "code")); }
        if (body.containsKey("description")) { sets.add("description=?"); params.add(str(body, "description")); }
        if (sets.isEmpty()) return Result.ok(Map.of("updated", false));
        params.add(id);
        jdbc.update("UPDATE department SET " + String.join(",", sets) + " WHERE id=?", params.toArray());
        return Result.ok(Map.of("updated", true));
    }

    @DeleteMapping("/{id}")
    @Transactional
    @OperationLog(value = "删除部门", type = "DELETE")
    public Result<Map<String, Object>> delete(@PathVariable Long id) {
        var deptRows = jdbc.queryForList("SELECT id, is_default FROM department WHERE id=? AND deleted=0", id);
        if (deptRows.isEmpty()) throw new IllegalArgumentException("部门不存在");
        var dept = deptRows.get(0);
        int isDefault = ((Number) dept.get("is_default")).intValue();
        if (isDefault == 1) throw new IllegalArgumentException("默认部门不能删除");

        // Check orphan contracts (DEPARTMENT visibility only visible to this dept)
        Integer orphanCount = jdbc.queryForObject(
                "SELECT COUNT(*) FROM contract_case WHERE department_id=? AND visibility='DEPARTMENT' AND deleted=0",
                Integer.class, id);
        if (orphanCount != null && orphanCount > 0) {
            throw new IllegalStateException(
                    "该部门下有 " + orphanCount + " 个仅本部门可见的合同，请先将它们改为全公司可见或指定其他部门，再删除本部门");
        }

        // Clean up SPECIFIED visibility references
        jdbc.update("DELETE FROM contract_department_visibility WHERE department_id=?", id);

        // Soft delete
        jdbc.update("UPDATE department SET deleted=1 WHERE id=?", id);

        // Migrate users to default department
        Long defaultDeptId = jdbc.queryForObject(
                "SELECT id FROM department WHERE is_default=1 AND deleted=0 LIMIT 1", Long.class);
        if (defaultDeptId != null) {
            jdbc.update("UPDATE t_user SET department_id=? WHERE department_id=?", defaultDeptId, id);
        }

        return Result.ok(Map.of("deleted", true));
    }

    private String str(Map<String, Object> map, String key) {
        Object v = map.get(key);
        return v == null ? "" : v.toString().trim();
    }
}
