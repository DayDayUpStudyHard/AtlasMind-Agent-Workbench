# AtlasMind 认证与权限体系 PRD v2

> 文档版本：v2.0  
> 日期：2026-08-09  
> 产品：AtlasMind Agent Workbench - ContractOps  
> 文档状态：待实施  
> 前版评审：v1 产品方向 8/10，安全边界和数据权限"可实施性"5/10  
> 本版修复：8 个 P0 问题，按四步重排实施计划，每一步骤均为代码级可执行

---

## 0. 权限矩阵（冻结）

在写任何代码之前，先冻结谁可以对什么资源做什么操作。本系统为单租户多部门模式。

### 0.1 角色定义

| 角色 | 英文 | 说明 |
|---|---|---|
| 管理员 | ADMIN | 全局所有资源 CRUD，可管理用户/部门/额度，可查看所有合同 |
| 普通用户 | USER | 只能访问自己有可见权限的合同，不能访问管理端 |

### 0.2 资源权限矩阵

| 资源 | 操作 | ADMIN | USER | 备注 |
|---|---|---|---|---|
| `contract_case` | 列表 | 全部 | 按可见性过滤 | 包括 portfolio/队列 |
| `contract_case` | 详情 | 全部 | 按可见性校验 | 404 若不可见 |
| `contract_case` | 创建 | ✅ | ✅ | USER 创建时 ownership=自己 |
| `contract_case` | 更新 | ✅ | ❌ | 仅管理员 |
| `contract_document` | 文档列表 | 全部 | 按合同可见性 | |
| `contract_document` | 文档内容 | 全部 | 按合同可见性 | |
| `contract_document` | 上传 | ✅ | ✅ | |
| `agent_run` | 列表 | 全部 | 按合同可见性 | |
| `agent_run` | 启动 | ✅ | ✅ | 受额度限制 |
| `agent_run` | SSE 流 | 全部 | 按 run 所属合同可见性 | |
| `agent_report` | 查看 | 全部 | 按合同可见性 | |
| `contract_review_finding` | 列表 | 全部 | 按合同可见性 | |
| `contract_review_finding` | 修改状态 | ✅ | ❌ | 仅管理员 |
| `contract_timeline_node` | 审核 | ✅ | ✅ | 需验证合同可见性 |
| `contract_fulfillment_check` | 查看 | 全部 | 按合同可见性 | |
| `contract_fulfillment_check` | 确认 | ✅ | ✅ | 需验证合同可见性 |
| `contract_obligation` | CRUD | ✅ | ❌ | 仅管理员 |
| `contract_intake` | 列表/确认 | ✅ | ✅ | 仅自己的 intake |
| 管理端 | 所有页面 | ✅ | ❌ | 路由级别拒绝 |
| `admin/users/**` | CRUD | ✅ | ❌ | |
| `admin/departments/**` | CRUD | ✅ | ❌ | |
| `admin/contracts/**` | 全合同管理 | ✅ | ❌ | |

### 0.3 管理员能力边界

- 可以查看所有合同（绕过可见性）
- 可以修改任意合同的可见性
- 可以创建/编辑/禁用用户
- 可以调整任意用户的额度
- 可以创建/编辑/软删除部门
- **不可以**代表用户发起 Agent Run（每次 run 必须有自己的 initiated_by）
- **不可以**删除/降级最后一个管理员

---

## 1. 实施步骤概览

```
Step 1: 认证基础（角色·状态·会话·安全引导）
   ↓
Step 2: 统一合同访问策略（ContractAccessPolicy 覆盖全资源面）
   ↓
Step 3: 额度 + Python 身份透传 + 前端 refresh
   ↓
Step 4: 审计补全 + 安全加固 + 测试
```

---

## 2. Step 1：认证基础

### 2.1 数据库变更

#### 2.1.1 t_user 扩展

```sql
-- 幂等加列（通过 SchemaInitializer.addColumnIfMissing 执行）
ALTER TABLE t_user ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'USER'
    COMMENT 'ADMIN|USER';
ALTER TABLE t_user ADD COLUMN department_id BIGINT DEFAULT NULL;
ALTER TABLE t_user ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'
    COMMENT 'ACTIVE|DISABLED';
ALTER TABLE t_user ADD INDEX idx_department (department_id);
ALTER TABLE t_user ADD INDEX idx_role_status (role, status);
```

#### 2.1.2 department 表

```sql
CREATE TABLE IF NOT EXISTS department (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    code VARCHAR(60) NOT NULL,
    is_default TINYINT NOT NULL DEFAULT 0 COMMENT '默认部门标记，禁止删除',
    description VARCHAR(500) DEFAULT '',
    deleted TINYINT NOT NULL DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_code (code),
    INDEX idx_deleted (deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

默认数据（幂等 upsert）：
```sql
INSERT INTO department (name, code, is_default, description) VALUES
('法务部', 'LEGAL', 1, '默认部门（系统初始化）')
ON DUPLICATE KEY UPDATE name=VALUES(name);
```

#### 2.1.3 refresh_token 表

```sql
CREATE TABLE IF NOT EXISTS user_refresh_token (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    token_hash CHAR(64) NOT NULL COMMENT 'SHA-256(token)',
    family VARCHAR(64) NOT NULL COMMENT 'token family 标识，rotation 时保持',
    expires_at DATETIME NOT NULL,
    revoked TINYINT NOT NULL DEFAULT 0,
    revoked_reason VARCHAR(64) DEFAULT NULL COMMENT 'LOGOUT|ROTATION|REUSE_DETECTED',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_family (user_id, family),
    INDEX idx_token_hash (token_hash),
    INDEX idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

#### 2.1.4 存量数据迁移

```sql
-- 确保法务部存在
INSERT IGNORE INTO department (id, name, code, is_default, description)
VALUES (1, '法务部', 'LEGAL', 1, '默认部门（系统初始化）');

-- 已有 admin 提权并归到法务部
UPDATE t_user SET role = 'ADMIN', department_id = 1 WHERE username = 'admin';

-- 存量合同：如果已有 department 字符串，尝试匹配 department 表
-- 匹配不上的 → 标记为待处理，不自动赋默认部门
-- （不执行批量 UPDATE，人工确认后再处理）
```

> **与 v1 的差异**：
> - 不创建 legacy 用户，存量合同的归属由管理员手动确认
> - 不执行 `UPDATE contract_case SET visibility='ALL'`，等 Step 2 的 ContractAccessPolicy 上线后由 ADMIN 逐个或批量设置
> - 迁移只做不破坏数据的 DDL + admin 提权
> - 不硬编码 ID=1，使用 `is_default=1` 标记默认部门

### 2.2 Sa-Token 权限提供器（StpInterface）

当前系统无 `StpInterface` 实现，`StpUtil.checkRole("ADMIN")` 不会生效。需要新增：

**新建文件**：`agent-server/.../config/SaTokenPermissionProvider.java`

```java
package com.atlasmind.config;

import cn.dev33.satoken.stp.StpInterface;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

@Component
@RequiredArgsConstructor
public class SaTokenPermissionProvider implements StpInterface {

    private final UserMapper userMapper;

    @Override
    public List<String> getPermissionList(Object loginId, String loginType) {
        return List.of();  // 当前不需要细粒度权限码
    }

    @Override
    public List<String> getRoleList(Object loginId, String loginType) {
        long userId = Long.parseLong(String.valueOf(loginId));
        User user = userMapper.selectById(userId);
        if (user == null || user.getRole() == null) return List.of();
        return List.of(user.getRole());  // "ADMIN" or "USER"
    }
}
```

### 2.3 登录改造

**修改文件**：`AuthController.java` `login()` 方法

增量逻辑：
```java
@PostMapping("/login")
public Result<Map<String, Object>> login(@Valid @RequestBody LoginDto dto,
                                          HttpServletResponse response) {
    User user = userService.login(dto.getUsername(), dto.getPassword());

    // 1. 检查用户状态
    if (!"ACTIVE".equals(user.getStatus())) {
        throw new IllegalStateException("账号已被禁用，请联系管理员");
    }

    // 2. 登录 Sa-Token
    StpUtil.login(user.getId());

    // 3. 生成 Refresh Token（随机 256-bit → hex，64 字符）
    String refreshToken = generateRefreshToken();  // SecureRandom → hex
    String tokenHash = sha256(refreshToken);
    String family = UUID.randomUUID().toString();
    userService.saveRefreshToken(user.getId(), tokenHash, family);

    // 4. 设置 httpOnly Cookie
    Cookie cookie = new Cookie("refresh_token", refreshToken);
    cookie.setHttpOnly(true);
    cookie.setSecure(false);   // 生产改为 true（HTTPS）
    cookie.setPath("/api/auth");
    cookie.setMaxAge(604800);  // 7 天
    cookie.setAttribute("SameSite", "Strict");
    response.addCookie(cookie);

    Map<String, Object> map = new HashMap<>();
    map.put("token", StpUtil.getTokenValue());         // access token → 前端存内存
    // 不再返回 user 的 password 字段（已有 @JsonProperty 保护）
    map.put("user", maskSensitive(user));              // 不含 password
    return Result.ok(map);
}
```

**修改文件**：`UserServiceImpl.java` `login()` 方法

当前 line 25：
```java
// 现有
User user = userMapper.selectOne(...);
if (user == null || !BCrypt.checkpw(...)) { throw ... }
user.setPassword(null);
return user;
```

增加 status 检查：
```java
if (!"ACTIVE".equals(user.getStatus())) {
    throw new IllegalStateException("账号已被禁用");
}
```

### 2.4 Refresh Token 端点（事务化 + FOR UPDATE）

**修改文件**：`AuthController.java`，新增方法：

```java
@PostMapping("/refresh")
public Result<Map<String, Object>> refresh(
        @CookieValue(value = "refresh_token", required = false) String refreshToken,
        HttpServletResponse response) {
    if (refreshToken == null || refreshToken.isBlank()) {
        throw new IllegalArgumentException("缺少 refresh token");
    }
    String tokenHash = sha256(refreshToken);

    // 委托给 UserService 的事务方法（find + revoke + save 在同一事务内）
    UserRefreshResult result = userService.rotateRefreshToken(tokenHash);
    // 内部逻辑：
    //   BEGIN TX
    //   SELECT * FROM user_refresh_token WHERE token_hash=? FOR UPDATE
    //   → 检查 revoked / expired / user status
    //   → UPDATE revoked=1, revoked_reason='ROTATION' WHERE token_hash=?
    //   → INSERT new token_hash, same family
    //   COMMIT

    // 新 Sa-Token access token
    StpUtil.login(result.userId());
    String newAccessToken = StpUtil.getTokenValue();

    // 新 cookie
    Cookie cookie = new Cookie("refresh_token", result.newToken());
    cookie.setHttpOnly(true);
    cookie.setPath("/api/auth");
    cookie.setMaxAge(604800);
    cookie.setAttribute("SameSite", "Strict");
    response.addCookie(cookie);

    return Result.ok(Map.of("token", newAccessToken));
}
```

**DDL 补全**（`user_refresh_token` 表）：
```sql
-- token_hash 必须加唯一索引，防止并发刷新竞态插入两条新 token
ALTER TABLE user_refresh_token ADD UNIQUE INDEX uk_token_hash (token_hash);
```

**并发安全分析**：
- 两个请求同时带同一个 refresh token → `SELECT FOR UPDATE` 排队
- 第一个拿到行锁 → 标记 revoked → insert 新 token → commit
- 第二个拿到行锁 → 看到 `revoked=1` → 触发 `REUSE_DETECTED` → 整个 family 撤销
- 结果：攻击者偷到 token 并 race 不过真正用户时，family 自动作废

### 2.5 登出端点

```java
@PostMapping("/logout")
public Result<?> logout(
        @CookieValue(value = "refresh_token", required = false) String refreshToken,
        HttpServletResponse response) {
    if (refreshToken != null && !refreshToken.isBlank()) {
        userService.revokeRefreshToken(sha256(refreshToken), "LOGOUT");
    }
    StpUtil.logout();

    // 清 cookie
    Cookie cookie = new Cookie("refresh_token", "");
    cookie.setHttpOnly(true);
    cookie.setPath("/api/auth");
    cookie.setMaxAge(0);
    response.addCookie(cookie);

    return Result.ok();
}
```

### 2.6 禁用用户时踢出会话

**修改文件**：`AdminUserController.java` 的 disable/enable 方法

```java
// 禁用用户
jdbcTemplate.update("UPDATE t_user SET status='DISABLED' WHERE id=?", userId);
StpUtil.kickout(userId);  // Sa-Token 踢出所有登录会话
userService.revokeAllRefreshTokens(userId);  // 撤销所有 refresh token

// 恢复用户
jdbcTemplate.update("UPDATE t_user SET status='ACTIVE' WHERE id=?", userId);
```

### 2.7 最后一个管理员保护

**修改文件**：`AdminUserController.java` 的删除/降级逻辑

```java
// 删除管理员前检查
if ("ADMIN".equals(user.getRole())) {
    int adminCount = jdbcTemplate.queryForObject(
        "SELECT COUNT(*) FROM t_user WHERE role='ADMIN' AND status='ACTIVE'",
        Integer.class);
    if (adminCount <= 1) {
        throw new IllegalStateException("不能删除或降级最后一个管理员");
    }
}
```

### 2.8 SaTokenConfig 路由改造

**修改文件**：`SaTokenConfig.java`

```java
@Override
public void addInterceptors(InterceptorRegistry registry) {
    // 前台接口：登录即可
    registry.addInterceptor(new SaInterceptor(handle -> StpUtil.checkLogin()))
            .addPathPatterns("/api/workspace/**", "/api/projects/**", "/api/kb/**",
                             "/api/upload/**", "/api/ai/**")
            .excludePathPatterns("/api/auth/login", "/api/auth/refresh");

    // 管理端接口：需要 ADMIN 角色
    registry.addInterceptor(new SaInterceptor(handle -> {
            StpUtil.checkLogin();
            StpUtil.checkRole("ADMIN");
        }))
        .addPathPatterns("/api/admin/**")
        .excludePathPatterns("/api/auth/login", "/api/auth/refresh");
}
```

### 2.9 Entity 变更

**修改文件**：`User.java`

```java
// 新增字段
private String role;         // ADMIN | USER
private Long departmentId;   // FK → department.id
private String status;       // ACTIVE | DISABLED
// + getter/setter（已有 @Data 自动生成）
```

### 2.10 管理员用户管理 API

**新建文件**：`AdminUserController.java`

```
GET    /api/admin/users            — 列表（分页、搜索、按角色/部门/状态过滤）
POST   /api/admin/users            — 创建（username/password/role/departmentId/quota）
GET    /api/admin/users/{id}       — 详情 + 额度
PUT    /api/admin/users/{id}       — 编辑（nickname/role/departmentId/status）
POST   /api/admin/users/{id}/disable  — 禁用（踢会话+撤 token）
POST   /api/admin/users/{id}/enable   — 启用
GET    /api/admin/users/{id}/quota/history  — 额度流水
POST   /api/admin/users/{id}/quota/adjust   — 调整额度
```

### 2.11 管理员部门管理 API

**新建文件**：`AdminDepartmentController.java`

```
GET    /api/admin/departments            — 列表
POST   /api/admin/departments            — 新建
PUT    /api/admin/departments/{id}       — 编辑
DELETE /api/admin/departments/{id}       — 软删除（is_default=1 拒绝删除）
```

软删除逻辑：
```java
// 1. 禁止删除默认部门
if (department.getIsDefault() == 1) throw ...;

// 2. 检查是否有合同仅对该部门可见（DEPARTMENT 模式），
//    如果存在，阻止删除并提示管理员先迁移这些合同的可见范围
int orphanCount = jdbcTemplate.queryForObject(
    "SELECT COUNT(*) FROM contract_case " +
    "WHERE department_id=? AND visibility='DEPARTMENT' AND deleted=0",
    Integer.class, deptId);
if (orphanCount != null && orphanCount > 0) {
    throw new IllegalStateException(
        "该部门下有 " + orphanCount + " 个仅本部门可见的合同，请先将它们改为全公司可见或指定其他部门，再删除本部门");
}

// 3. 检查 contract_department_visibility 中对该部门的引用
int specRefCount = jdbcTemplate.queryForObject(
    "SELECT COUNT(*) FROM contract_department_visibility WHERE department_id=?",
    Integer.class, deptId);
// specRefCount > 0 不会阻止删除（Grill Q10），但清理 visibility 引用
if (specRefCount != null && specRefCount > 0) {
    jdbcTemplate.update(
        "DELETE FROM contract_department_visibility WHERE department_id=?", deptId);
    // 注意：这不会让合同无人可见——visibility=SPECIFIED 的合同
    // 至少需要指定一个部门，SQL 层面由 uk_contract_dept UNIQUE 保证至少一行
    // 若管理员先删部门 → 对应 visibility 行被删 → 合同可能变无人可见
    // 解决：SPECIFIED 模式下检查至少还有一个有效部门引用，否则拒绝删除
}

// 4. 软删除部门
jdbcTemplate.update("UPDATE department SET deleted=1 WHERE id=?", deptId);

// 5. 该部门下的用户迁入默认部门
Long defaultDeptId = getDefaultDepartmentId();
jdbcTemplate.update("UPDATE t_user SET department_id=? WHERE department_id=?", defaultDeptId, deptId);
```

---

## 3. Step 2：统一合同访问策略

### 3.1 核心问题

当前 `ContractWorkspaceController` 的 30+ 个端点中，绝大多数不传入或检查当前用户身份：

| 端点 | 当前行为 | 问题 |
|---|---|---|
| `GET /contracts` | 全量查询 | 无可见性过滤 |
| `GET /contracts/{caseId}` | `getCase(caseId)` | 不校验不可见合同 |
| `GET /contracts/{caseId}/documents` | 全量 | 不校验 |
| `GET /contracts/{caseId}/documents/{id}/content` | 全量 | 不校验 |
| `GET /contracts/{caseId}/runs` | 全量 | Agent Run 信息泄露 |
| `GET /contracts/runs/{runId}` | `getRun(runId)` | 不校验跑所属合同 |
| `GET /contracts/runs/{runId}/stream` | SSE 直连 | 不校验 |
| `POST /contracts/{caseId}/runs` | 直接发起 | 无额度检查 |
| `PATCH /contracts/findings/{findingId}` | 直接修改 | 不校验合同所属 |
| `PATCH /contracts/{caseId}/elements/{id}/review` | 直接审核 | 不校验合同可见性 |

### 3.2 数据模型：稳定归属

**核心决策**：合同在创建时写入不可变的 `department_id` 快照，不使用 `creator.department_id`（避免换部门后历史数据飘移）。

**contract_case 扩展**：
```sql
-- 注意：不能直接 NOT NULL DEFAULT 'ALL'，否则存量合同被静默设为全可见
-- 与"管理员人工确认"流程冲突
ALTER TABLE contract_case ADD COLUMN visibility VARCHAR(16) NOT NULL DEFAULT 'LEGACY_REVIEW'
    COMMENT 'LEGACY_REVIEW|DEPARTMENT|SPECIFIED|ALL';
ALTER TABLE contract_case ADD COLUMN creator_id BIGINT DEFAULT NULL COMMENT '上传人';
ALTER TABLE contract_case ADD COLUMN maintainer_id BIGINT DEFAULT NULL COMMENT '维护人';
ALTER TABLE contract_case ADD COLUMN department_id BIGINT DEFAULT NULL
    COMMENT '创建时的部门快照（不可变）';

ALTER TABLE contract_case ADD INDEX idx_visibility (visibility);
ALTER TABLE contract_case ADD INDEX idx_creator (creator_id);
ALTER TABLE contract_case ADD INDEX idx_department (department_id);
```

**LEGACY_REVIEW 机制**：
- 加列时存量合同自动得到 `visibility='LEGACY_REVIEW'`
- `LEGACY_REVIEW` 的语义：**临时全可见**（等价于 ALL），直到管理员手动确认
- 管理端合同列表对 `LEGACY_REVIEW` 合同显示黄色标签"待确认可见范围"
- 管理员可以逐个或批量将 `LEGACY_REVIEW` 改为 `ALL` / `DEPARTMENT` / `SPECIFIED`
- `ContractAccessPolicy` 将 `LEGACY_REVIEW` 视为 `ALL`（过渡期全可见）
- 目标：上线 30 天内所有存量合同退出 `LEGACY_REVIEW` 状态

```sql
-- 一次性迁移：匹配 department 字符串 → department_id
-- 匹配不上的不填，不影响 LEGACY_REVIEW 的过渡可见性
UPDATE contract_case c
JOIN department d ON d.name = c.department AND d.deleted = 0
SET c.department_id = d.id
WHERE c.department IS NOT NULL AND c.department_id IS NULL;
```

**contract_department_visibility 关联表**：
```sql
CREATE TABLE IF NOT EXISTS contract_department_visibility (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    contract_id BIGINT NOT NULL,
    department_id BIGINT NOT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_contract_dept (contract_id, department_id),
    INDEX idx_dept_contract (department_id, contract_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 3.3 ContractAccessPolicy 统一入口

**新建文件**：`agent-server/.../service/ContractAccessPolicy.java`

```java
package com.atlasmind.service;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.entity.User;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.Map;

@Component
@RequiredArgsConstructor
public class ContractAccessPolicy {

    private final JdbcTemplate jdbc;
    private final UserService userService;

    /**
     * 检查当前用户是否可以访问指定合同。
     * @throws AccessDeniedException 如果不可访问
     */
    public void checkAccess(Long caseId) {
        long userId = StpUtil.getLoginIdAsLong();
        if (isAdmin(userId)) return;  // 管理员全局通行

        Map<String, Object> contract = first(jdbc.queryForList(
            "SELECT id, visibility, department_id FROM contract_case WHERE id=? AND deleted=0",
            caseId));
        if (contract == null) throw notFound("合同不存在");

        String visibility = (String) contract.getOrDefault("visibility", "ALL");
        Long contractDeptId = numberAsLongOrNull(contract.get("department_id"));
        Long userDeptId = getCurrentUserDepartmentId(userId);

        if ("ALL".equals(visibility) || "LEGACY_REVIEW".equals(visibility)) return;
        if ("DEPARTMENT".equals(visibility)) {
            if (contractDeptId != null && contractDeptId.equals(userDeptId)) return;
        }
        if ("SPECIFIED".equals(visibility)) {
            // 管理员允许通过（上方已处理）
            if (userDeptId != null) {
                int count = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM contract_department_visibility " +
                    "WHERE contract_id=? AND department_id=?",
                    Integer.class, caseId, userDeptId);
                if (count != null && count > 0) return;
            }
        }
        throw notFound("合同不存在");  // 不暴露存在但无权限的合同
    }

    /**
     * 构建前台合同查询的可见性 WHERE 子句。
     * @return SQL 片段，如 "AND (...)"，参数追加到 params
     */
    public String buildVisibilityFilter(List<Object> params) {
        long userId = StpUtil.getLoginIdAsLong();
        if (isAdmin(userId)) return "";  // 管理员无限制

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

    public boolean isAdmin(long userId) {
        User user = userService.getById(userId);
        return user != null && "ADMIN".equals(user.getRole());
    }

    private Long getCurrentUserDepartmentId(long userId) {
        User user = userService.getById(userId);
        return user != null ? user.getDepartmentId() : null;
    }

    private AccessDeniedException notFound(String msg) {
        return new AccessDeniedException(msg);  // 始终返回 404，不暴露权限信息
    }
}
```

### 3.4 全资源面接入

**修改文件**：`ContractWorkspaceController.java`，所有读/写端点注入 `ContractAccessPolicy` 并调用：

| 端点 | 注入方式 | 备注 |
|---|---|---|
| `GET /contracts` | `listCases()` 内嵌 `buildVisibilityFilter()` | |
| `GET /contracts/portfolio` | 内嵌 `buildVisibilityFilter()` | portfolio 统计也需隔离 |
| `GET /contracts/work-queues/summary` | 内嵌 `buildVisibilityFilter()` | |
| `GET /contracts/work-queues` | 内嵌 `buildVisibilityFilter()` | |
| `GET /contracts/document-pipelines/recent` | 内嵌 `buildVisibilityFilter()` | 最近文档流水线 |
| `POST /contracts` | 登录即可 | 创建时不校验可见性 |
| `POST /contracts/intakes` | 登录即可 `created_by=StpUtil.getLoginIdAsLong()` | intake 不绑定 caseId |
| `POST /contracts/intakes/upload` | 同上 | |
| `GET /contracts/intakes/{intakeId}` | `created_by=StpUtil.getLoginIdAsLong()` | 已有此校验 |
| `POST /contracts/intakes/{intakeId}/retry` | 同上 `created_by` 校验 | |
| `POST /contracts/intakes/{intakeId}/confirm` | 同上 `created_by` 校验 | |
| `GET /contracts/{caseId}` | `policy.checkAccess(caseId)` | |
| `PUT /contracts/{caseId}` | `policy.checkAccess(caseId)` | |
| `GET /contracts/{caseId}/documents` | `policy.checkAccess(caseId)` | |
| `GET /contracts/{caseId}/documents/{id}/content` | `policy.checkAccess(caseId)` | |
| `POST /contracts/{caseId}/documents` | `policy.checkAccess(caseId)` | |
| `GET /contracts/{caseId}/runs` | `policy.checkAccess(caseId)` | |
| `POST /contracts/{caseId}/runs` | `policy.checkAccess(caseId)` + 额度检查 | |
| `GET /contracts/runs/{runId}` | 查 `agent_run.subject_id` → `policy.checkAccess(subjectId)` | |
| `GET /contracts/runs/{runId}/stream` | 查 `agent_run.subject_id` → `policy.checkAccess(subjectId)` | SSE 流 |
| `POST /contracts/runs/{runId}/actions/{actionId}/approval` | 查 `agent_action → agent_run.subject_id` → `policy.checkAccess(subjectId)` | 审批动作 |
| `PATCH /contracts/findings/{findingId}` | 查 `contract_review_finding.case_id` → `policy.checkAccess(caseId)` | |
| `PATCH /contracts/{caseId}/elements/{id}/review` | `policy.checkAccess(caseId)` | |
| `PATCH /contracts/{caseId}/facts/review` | `policy.checkAccess(caseId)` | |
| `POST /contracts/{caseId}/timeline/{nodeId}/fulfillment-checks` | `policy.checkAccess(caseId)` | 启动履约核验 |
| `PATCH /contracts/{caseId}/timeline/{nodeId}/review` | `policy.checkAccess(caseId)` | |
| `PATCH /contracts/fulfillment-checks/{checkId}/confirmation` | 查 `contract_fulfillment_check.case_id` → `policy.checkAccess(caseId)` | 履约核验确认 |
| `GET /contracts/{caseId}/timeline/{nodeId}/evidence-links` | `policy.checkAccess(caseId)` | |
| `PUT /contracts/{caseId}/timeline/{nodeId}/evidence-links` | `policy.checkAccess(caseId)` | |
| `GET /contracts/{caseId}/obligations` | `policy.checkAccess(caseId)` | |
| `POST /contracts/{caseId}/obligations` | `policy.checkAccess(caseId)` | |
| `PUT /contracts/obligations/{obligationId}` | 查 `contract_obligation.case_id` → `policy.checkAccess(caseId)` | |
| `POST /contracts/{caseId}/fulfillment-evidence` | `policy.checkAccess(caseId)` | |
| `GET /contracts/reminders` | 内嵌 `buildVisibilityFilter()` | |
| `GET /contracts/memories/{memoryId}` | 登录即可 | 项目记忆不按合同隔离 |

**修改文件**：`ContractCaseServiceImpl.java`

- `portfolio()` / `listCases()` / `listWorkQueue()` 等列表方法 → 嵌入 `buildVisibilityFilter()`
- 详情类方法在各查询前不需要额外改（Controller 层已校验），但作为纵深防御，在 `getCase()` 内也增加一次 `checkAccess()` 调用

**修改文件**：`ContractAdminController.java` — 管理端不加 `ContractAccessPolicy`，ADMIN 全局可见。

### 3.5 合同创建时填充字段

**修改文件**：`ContractCaseServiceImpl.java` `createCase()`

```java
// 在 INSERT 语句中增加字段
Long userId = StpUtil.getLoginIdAsLong();
User user = userService.getById(userId);

// 新增 SQL 字段：creator_id, maintainer_id, department_id, visibility
// department_id = 创建者的 department_id（不可变快照）
jdbc.update("""
    INSERT INTO contract_case (..., creator_id, maintainer_id, department_id, visibility)
    VALUES (...,?,?,?,?)
    """, ..., userId, userId, user.getDepartmentId(), str(request, "visibility"));
```

### 3.6 分类讨论

**已有的 `contract_case.department` VARCHAR 字段与新的 `department_id` BIGINT 的关系**：
- `department` 列保留不动（向后兼容），在 ContractAdminController 中仍可读写
- `department_id` 作为新的规范化外键列，由系统自动填充
- 过渡期：`ContractAccessPolicy.checkAccess()` 优先使用 `department_id`，为 NULL 时 fallback 到 `department` 字符串匹配

**`contract_document.upload_by` 与新的 `contract_case.creator_id` 的关系**：
- `creator_id` 是合同创建者（intake 确认时写一次）
- `maintainer_id` 是当前维护人（可由管理员修改）
- `upload_by` 是文档上传人（不变），保留不动

**agent_run.initiated_by 扩展**：
```sql
-- 记录谁发起了 Agent Run（额度归属依据）
ALTER TABLE agent_run ADD COLUMN initiated_by BIGINT DEFAULT NULL COMMENT '发起人 user_id';
-- 存量 run 回填
UPDATE agent_run ar
JOIN contract_case c ON c.id = ar.subject_id AND ar.subject_type = 'CONTRACT_CASE'
SET ar.initiated_by = c.creator_id
WHERE ar.initiated_by IS NULL;
```

---

## 4. Step 3：额度 + Python 身份透传 + 前端

### 4.1 额度模型

#### 4.1.1 表结构

```sql
CREATE TABLE IF NOT EXISTS user_quota (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    total_quota INT NOT NULL DEFAULT 0,
    used_count INT NOT NULL DEFAULT 0,
    reserved_count INT NOT NULL DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS quota_transaction (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount INT NOT NULL COMMENT '变动量',
    type VARCHAR(32) NOT NULL COMMENT 'ALLOCATE|RESERVE|CONFIRM|REFUND|ADMIN_ADJUST',
    balance_after INT NOT NULL COMMENT '变动后 available = total - used - reserved',
    operator_id BIGINT COMMENT '管理员操作时记录',
    run_id BIGINT COMMENT '关联 agent_run',
    remark VARCHAR(500) DEFAULT '',
    idempotency_key VARCHAR(128) DEFAULT NULL COMMENT '幂等键（run_id + type）',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_time (user_id, create_time),
    INDEX idx_run (run_id),
    UNIQUE KEY uk_idempotency (idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

#### 4.1.2 额度服务

**新建文件**：`agent-server/.../service/QuotaService.java`

```java
public class QuotaService {

    /**
     * 预扣：开始 Agent Run 时调用。
     * 使用 SELECT ... FOR UPDATE 保证原子性。
     * @throws QuotaExceededException 额度不足
     */
    @Transactional
    public void reserve(Long userId, Long runId) {
        UserQuota quota = quotaMapper.selectForUpdate(userId);
        if (quota == null) throw new IllegalStateException("用户无额度记录");

        int available = quota.getTotalQuota() - quota.getUsedCount() - quota.getReservedCount();
        if (available <= 0) throw new QuotaExceededException("分析额度已用完");

        quota.setReservedCount(quota.getReservedCount() + 1);
        quotaMapper.updateById(quota);

        // 记流水
        insertTransaction(userId, -1, "RESERVE",
            quota.getTotalQuota() - quota.getUsedCount() - quota.getReservedCount(),
            null, runId, "run:" + runId + ":RESERVE");
    }

    /**
     * 确认：Agent Run 成功后调用。
     */
    @Transactional
    public void confirm(Long userId, Long runId) {
        UserQuota quota = quotaMapper.selectForUpdate(userId);
        quota.setReservedCount(Math.max(0, quota.getReservedCount() - 1));
        quota.setUsedCount(quota.getUsedCount() + 1);
        quotaMapper.updateById(quota);

        insertTransaction(userId, 0, "CONFIRM",
            quota.getTotalQuota() - quota.getUsedCount() - quota.getReservedCount(),
            null, runId, "run:" + runId + ":CONFIRM");
    }

    /**
     * 退还：Agent Run 失败后调用。
     */
    @Transactional
    public void refund(Long userId, Long runId) {
        UserQuota quota = quotaMapper.selectForUpdate(userId);
        quota.setReservedCount(Math.max(0, quota.getReservedCount() - 1));
        quotaMapper.updateById(quota);

        insertTransaction(userId, +1, "REFUND",
            quota.getTotalQuota() - quota.getUsedCount() - quota.getReservedCount(),
            null, runId, "run:" + runId + ":REFUND");
    }

    /**
     * 释放：崩溃恢复时调用（幂等）。
     * 只释放在 run 启动后 N 分钟内仍未 confirm 的预扣。
     */
    @Transactional
    public void releaseStaleReservations() {
        // SELECT * FROM quota_transaction
        // WHERE type='RESERVE' AND create_time < NOW() - INTERVAL 1 HOUR
        //   AND run_id IN (
        //     SELECT id FROM agent_run WHERE status IN ('FAILED','CANCELLED')
        //   )
        // FOR UPDATE
        // → 逐条 refund
    }

    /**
     * 管理员调整额度。
     */
    @Transactional
    public void adjust(Long userId, int delta, Long operatorId, String remark) {
        UserQuota quota = quotaMapper.selectForUpdate(userId);
        if (quota.getTotalQuota() + delta < quota.getUsedCount()) {
            throw new IllegalArgumentException("不能扣到低于已用量");
        }
        quota.setTotalQuota(quota.getTotalQuota() + delta);
        quotaMapper.updateById(quota);

        insertTransaction(userId, delta, "ADMIN_ADJUST",
            quota.getTotalQuota() - quota.getUsedCount() - quota.getReservedCount(),
            operatorId, null, null);
    }
}
```

#### 4.1.3 接入 Agent Run 生命周期

**修改文件**：`ContractCaseServiceImpl.java` `startRun()`

```java
// 在 dispatchToPython 之前：
if (!quotaService.hasQuota(userId)) {
    throw new QuotaExceededException("合同分析额度不足");
}
quotaService.reserve(userId, runId);
jdbcTemplate.update("UPDATE agent_run SET initiated_by=? WHERE id=?", userId, runId);
```

**修改文件**：`ContractCaseServiceImpl.java` `dispatchToPython()` — 在 `agent_run` 的 payload 中增加 `X-User-Id`

**Python 侧回调 / Java 端 polling**：当 `agent_run.status` 变为 `COMPLETED` 时调 `quotaService.confirm()`，变为 `FAILED` 时调 `quotaService.refund()`

**崩溃恢复**：定时任务（`@Scheduled`）每 5 分钟调 `quotaService.releaseStaleReservations()`

### 4.2 Python 鉴权

#### 4.2.1 现状确认

- Java → Python：已使用 `X-Internal-Token` header（`HttpAiGateway.java:144`）
- Python 侧：已有 `_check_internal_token()`（`routes.py:54-57`）
- Docker Compose：Python 18088 端口映射到宿主机（`docker-compose.yml:122`）

#### 4.2.2 改造方案

**不迁移** header 名称（保留 `X-Internal-Token`，不改成 `Authorization: Bearer`）。变更：

**1. Python fail-closed**：

修改 `routes.py` `_check_internal_token()`：

```python
def _check_internal_token(token: str | None) -> None:
    expected = settings.internal_token
    if not expected:
        # 未配置时抛出异常（生产必须配置）
        raise HTTPException(status_code=500, detail="SERVICE_TOKEN not configured")
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Forbidden")
```

当前行为是 `if expected and (...)`—未配置时静默放行。改为 fail-closed：未配置即拒绝。

**2. Docker Compose 移除 Python 端口**：

```yaml
# docker-compose.yml ai-service 段
# 删除：
#   ports:
#     - "${AI_SERVICE_PORT:-18088}:18088"
# 改为只在内部 Docker 网络可达：
#   expose:
#     - "18088"
```

Java 通过 Docker 内部网络 `http://ai-service:18088` 访问 Python。

**3. Java 传身份 Header（信任 StpUtil，不信任前端 payload）**：

修改 `HttpAiGateway.java`，`startAgentRun()` 和 `resumeAgentRun()`：

```java
// ⚠️ userId 和 departmentId 必须从 StpUtil 获取，不可信任前端 payload
long userId = StpUtil.getLoginIdAsLong();
User user = userService.getById(userId);

// 注入到 payload（不修改入参 payload 的 userId 字段——只追加网关侧注入的字段）
Map<String, Object> enrichedPayload = new LinkedHashMap<>(payload);
enrichedPayload.put("_gateway_userId", userId);
enrichedPayload.put("_gateway_departmentId", user.getDepartmentId());

// HTTP Header 传身份给 Python
builder.header("X-User-Id", String.valueOf(userId));
if (user.getDepartmentId() != null) {
    builder.header("X-Department-Id", String.valueOf(user.getDepartmentId()));
}
// X-Internal-Token 已有（当前不变）
builder.header("X-Internal-Token", internalToken);
```

Python 侧**仍信任 X-Internal-Token 校验后的 X-User-Id**：
- Python 不需要独立验证 X-User-Id，因为只有通过 X-Internal-Token 的请求才能到达
- Python 对 X-User-Id 作只读使用（记日志、关联 run.creator），不作为鉴权依据

**4. Python 端信任来源**：

Python 侧使用 `X-User-Id` 和 `X-Department-Id` Header 时注意：这些值来自 Java 网关，**不可由前端直接传入**。Python 仅接受来自 `X-Internal-Token` 校验通过的请求中的这些 Header。

**5. Python CORS 修复**：

当前 `main.py` 使用 `allow_origins=["*"]` + `allow_credentials=True`，这是浏览器规范禁止的组合。改为明确 Origin 白名单，以配合前端 httpOnly Cookie refresh：

```python
# main.py 修改
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # agent-front 开发
        "http://localhost:5174",   # agent-admin 开发
        "http://localhost:18080",  # Java 网关
        # 生产环境改为 nginx 域名
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

注意：`allow_origins` 不能和 `allow_credentials=True` 一起用 `"*"`。浏览器会直接拒绝。改用显式列表。

### 4.3 前端 Refresh Token + 路由

#### 4.3.1 Token 存储策略

| 项目 | 存储方式 |
|---|---|
| Access Token | JS 内存 `ref(StpUtil.getTokenValue())` |
| Refresh Token | httpOnly Cookie（由 Java Set-Cookie） |

前端 `api/index.js` 改造：

```javascript
// 全局 access token（内存，不持久化）
const accessToken = ref(null)

// 登录成功后：
//   accessToken.value = response.data.data.token
//   （refresh token 由 httpOnly cookie 自动处理）

// 请求拦截器
api.interceptors.request.use(config => {
  if (accessToken.value) {
    config.headers['atlasmind-token'] = accessToken.value
  }
  return config
})

// 响应拦截器 — 刷新队列
let isRefreshing = false
let refreshQueue = []

api.interceptors.response.use(
  response => response,
  async error => {
    const originalRequest = error.config
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (!isRefreshing) {
        isRefreshing = true
        try {
          const res = await axios.post('/api/auth/refresh', {}, { withCredentials: true })
          accessToken.value = res.data.data.token
          // 重放队列
          const token = accessToken.value
          refreshQueue.forEach(([resolve, _reject]) => resolve(token))
          refreshQueue = []
          // 重放当前请求
          originalRequest._retry = true
          originalRequest.headers['atlasmind-token'] = token
          return api(originalRequest)
        } catch (refreshError) {
          // refresh 失败 → 清队列 + 跳登录
          refreshQueue.forEach(([_resolve, reject]) => reject(refreshError))
          refreshQueue = []
          accessToken.value = null
          router.push('/login')
          return Promise.reject(refreshError)
        } finally {
          isRefreshing = false
        }
      } else {
        // 排队
        return new Promise((resolve, reject) => {
          refreshQueue.push([resolve, reject])
        }).then(token => {
          originalRequest._retry = true
          originalRequest.headers['atlasmind-token'] = token
          return api(originalRequest)
        })
      }
    }
    return Promise.reject(error)
  }
)
```

#### 4.3.2 路由守卫 + 启动恢复

```javascript
router.beforeEach(async (to, from, next) => {
  // 公开页面直接放行
  if (to.meta.public) return next()

  // 已有 token → 放行
  if (accessToken.value) {
    if (to.path === '/login') return next('/')
    return next()
  }

  // 无 token → 尝试 refresh
  try {
    const res = await axios.post('/api/auth/refresh', {}, { withCredentials: true })
    accessToken.value = res.data.data.token
    if (to.path === '/login') return next('/')
    return next()
  } catch {
    // refresh 也失败 → 登录页
    if (to.path !== '/login') return next('/login')
    return next()
  }
})
```

注意：路由守卫 await refresh 时页面会白屏几毫秒，对于首次访问是正常行为。对于 Tabs 恢复场景（Ctrl+Shift+T），refresh 从 cookie 拿 token 重新登录，用户无感。

#### 4.3.3 前端 UI 改造清单

**agent-front**：

| 文件 | 改造 |
|---|---|
| `AppHeader.vue` | 顶部展示：用户昵称 + 部门名称 + 登出按钮（调 `/api/auth/logout`） |
| `ContractPortfolioView.vue` | 列表加"上传人"列（`creatorName`），API 自动按可见性过滤 |
| `ContractCaseView.vue` | 显示上传人/维护人/可见性标签 |
| `ContractCreateView.vue` | 上传表单加"可见性"选择 + 多部门选择器 |
| `api/index.js` | token 内存化 + 刷新队列 + `/auth/refresh` + `/auth/logout` |
| `router/index.js` | 启动恢复 + 内存 token 判断 |

**agent-admin**：

| 文件 | 改造 |
|---|---|
| `views/Users.vue` | **新建**：用户管理页（CURD + 额度调整） |
| `views/Departments.vue` | **新建**：部门管理页（CRUD + 软删除保护） |
| `AdminLayout.vue` | 侧栏菜单 + "用户管理"+"部门管理"入口 + 管理端路由守卫拒绝 USER |
| `ContractManage.vue` | 列表加"所属用户""所属部门""可见性"列 + 可编辑可见性 |
| `api/index.js` | 同前台 |

---

## 5. Step 4：审计补全 + 安全加固 + 测试

### 5.1 审计日志扩展

**现状**：`OperationLogAspect` → Redis Stream `oplog:stream` → `OperationLogConsumer` 落 `t_operation_log`

**扩展 t_operation_log**：
```sql
ALTER TABLE t_operation_log ADD COLUMN operator_id BIGINT DEFAULT NULL;
ALTER TABLE t_operation_log ADD COLUMN target_type VARCHAR(64) DEFAULT NULL;
ALTER TABLE t_operation_log ADD COLUMN target_id BIGINT DEFAULT NULL;
ALTER TABLE t_operation_log ADD COLUMN target_label VARCHAR(256) DEFAULT NULL;
ALTER TABLE t_operation_log ADD COLUMN old_value_json LONGTEXT;
ALTER TABLE t_operation_log ADD COLUMN new_value_json LONGTEXT;
ALTER TABLE t_operation_log ADD INDEX idx_target (target_type, target_id);
ALTER TABLE t_operation_log ADD INDEX idx_operator (operator_id, create_time);
```

**切面改造**：
- `@OperationLog` 注解增加可选 `targetType`、`targetId` 参数，或从方法参数中自动提取
- `args` 序列化时过滤敏感字段：password、token、refresh_token→星号替换
- `args` 截断长度从 200 调整为 2000（当前太短，丢失有用信息）

**Entity 同步**：`OperationLog.java` 增加对应字段

### 5.2 关键操作审计清单

确保以下操作都有 `@OperationLog` 覆盖：

| 操作 | Controller 方法 | 注解 |
|---|---|---|
| 创建用户 | `AdminUserController.create` | `@OperationLog(value="创建用户", type="CREATE")` |
| 禁用/启用用户 | `AdminUserController.disable/enable` | `@OperationLog(value="禁用用户", type="UPDATE")` |
| 调整额度 | `AdminUserController.adjustQuota` | `@OperationLog(value="调整额度", type="UPDATE")` |
| 修改用户角色 | `AdminUserController.update` | `@OperationLog(value="修改用户角色", type="UPDATE")` |
| 创建部门 | `AdminDepartmentController.create` | `@OperationLog(value="创建部门", type="CREATE")` |
| 删除部门 | `AdminDepartmentController.delete` | `@OperationLog(value="删除部门", type="DELETE")` |
| 修改合同可见性 | `ContractAdminController` | 新增方法 + `@OperationLog` |

### 5.3 安全加固清单

| 项 | 操作 |
|---|---|
| Python fail-closed | `_check_internal_token()` 未配置时 500 |
| Python 端口不暴露 | `docker-compose.yml` 移除 `ports: 18088:18088` |
| 敏感信息脱敏 | 日志中 password/token 替换为 `***` |
| 密码传输 | 当前已通过 HTTPS（需确认 nginx 配置）；若非 HTTPS，Token 不以明文在 URL 中传输 |
| CORS | 确保 `Access-Control-Allow-Credentials: true` + 明确 Origin 白名单 |
| Cookie | 生产环境 `Secure` 标志（需 HTTPS） |

---

## 6. 测试计划

### 6.1 功能测试用例

| # | 场景 | 预期 |
|---|---|---|
| T-1 | 未登录访问前台 | 跳转 `/login` |
| T-2 | 登录 admin | 获得 access token + cookie |
| T-3 | 页面刷新 | 自动 refresh，token 恢复 |
| T-4 | USER 访问 `/api/admin/users` | 403 |
| T-5 | USER 访问管理端路由 | 跳转登录页或不渲染 |
| T-6 | USER 合同列表 | 只看到 visibility=ALL + 本部门 + 本部门 SPECIFIED |
| T-7 | USER 直接 URL `/contracts/999`（不可见合同） | 404 |
| T-8 | USER 直接 `/contracts/999/documents` | 404 |
| T-9 | USER 直接 `/contracts/runs/123/stream`（不可见合同run） | 404 |
| T-10 | 管理员合同列表 | 看到全部 |
| T-11 | 上传合同时 `creator_id`、`department_id` 自动填充 | 创建后可查 |
| T-12 | 额度预扣 → 分析成功 | used+1, reserved 不变 |
| T-13 | 额度预扣 → 分析失败 | 额度退还不扣 |
| T-14 | 额度用完 | 拒绝发起新分析 |
| T-15 | 禁用用户 | 已登录被踢出 |
| T-16 | 删除部门 | 用户迁默认部门 |
| T-17 | 删除默认部门 | 被拒绝 |
| T-18 | 降级最后一个管理员 | 被拒绝 |
| T-19 | Refresh token rotation | 旧 token 失效 |
| T-20 | 重放已 rotation 的 refresh token | 被拒绝 + family 全部撤销 |

### 6.2 安全测试用例

| # | 场景 | 预期 |
|---|---|---|
| S-1 | 直接调 Python `/api/agent/run` 不带 X-Internal-Token | 403 |
| S-2 | 直接调 Python 带错误 token | 403 |
| S-3 | USER 伪造 `X-User-Id` 调 Python | 不可达（Python 不暴露公网） |
| S-4 | XSS 读 `document.cookie` 拿 refresh token | 读不到（httpOnly） |
| S-5 | 用过期 access token 请求 | 401 → 自动 refresh |

---

## 7. 文件变更清单

### 7.1 新建文件

| 文件 | 说明 |
|---|---|
| `agent-server/.../entity/Department.java` | 部门实体 |
| `agent-server/.../entity/UserQuota.java` | 额度实体 |
| `agent-server/.../entity/QuotaTransaction.java` | 额度流水实体 |
| `agent-server/.../mapper/DepartmentMapper.java` | 部门 Mapper（MyBatis-Plus） |
| `agent-server/.../mapper/UserQuotaMapper.java` | 额度 Mapper |
| `agent-server/.../service/DepartmentService.java` | 部门服务接口 |
| `agent-server/.../service/impl/DepartmentServiceImpl.java` | 部门服务实现 |
| `agent-server/.../service/QuotaService.java` | 额度服务（含事务） |
| `agent-server/.../service/ContractAccessPolicy.java` | 统一合同访问策略 |
| `agent-server/.../controller/admin/AdminUserController.java` | 管理员用户管理 |
| `agent-server/.../controller/admin/AdminDepartmentController.java` | 管理员部门管理 |
| `agent-server/.../config/SaTokenPermissionProvider.java` | 角色提供器 |
| `agent-admin/src/views/Users.vue` | 用户管理页 |
| `agent-admin/src/views/Departments.vue` | 部门管理页 |

### 7.2 修改文件

| 文件 | 变更摘要 |
|---|---|
| `agent-server/.../entity/User.java` | +role, departmentId, status |
| `agent-server/.../entity/OperationLog.java` | +operatorId, targetType, targetId, targetLabel, old/new Value |
| `agent-server/.../service/UserService.java` | +findByUsername, saveRefreshToken, revokeToken 等方法 |
| `agent-server/.../service/impl/UserServiceImpl.java` | 实现+登录检查 status |
| `agent-server/.../controller/AuthController.java` | +refresh, logout; 登录逻辑增强 |
| `agent-server/.../config/SaTokenConfig.java` | 分前台/管理端路由, 角色校验 |
| `agent-server/.../config/DataInitializer.java` | admin 初始化时设置 role=ADMIN, departmentId |
| `agent-server/.../config/AgentWorkbenchSchemaInitializer.java` | +所有 DDL |
| `agent-server/.../controller/ContractWorkspaceController.java` | 全端点接入 ContractAccessPolicy |
| `agent-server/.../service/impl/ContractCaseServiceImpl.java` | 列表/详情加可见性过滤, startRun 加额度检查 |
| `agent-server/.../controller/ContractAdminController.java` | +可见性编辑, +部门过滤 |
| `agent-server/.../gateway/HttpAiGateway.java` | +X-User-Id/X-Department-Id header |
| `agent-server/.../aspect/OperationLogAspect.java` | +敏感信息脱敏, +args 长度调整 |
| `docker-compose.yml` | Python 端口移除宿主机映射 |
| `tools/.../routes.py` | `_check_internal_token()` fail-closed |
| `agent-front/src/api/index.js` | 内存 token + 刷新队列 |
| `agent-front/src/router/index.js` | 启动恢复 |
| `agent-front/src/components/AppHeader.vue` | 部门 + 登出 |
| `agent-front/src/views/ContractPortfolioView.vue` | 可见性过滤 + 上传人列 |
| `agent-front/src/views/ContractCreateView.vue` | 可见性选择 |
| `agent-front/src/views/ContractCaseView.vue` | 显示上传人/维护人 |
| `agent-admin/src/api/index.js` | 同前台 |
| `agent-admin/src/components/AdminLayout.vue` | 菜单扩展 + 角色守卫 |
| `agent-admin/src/views/ContractManage.vue` | 归属 + 可见性展示 |

---

## 8. 验收标准

| # | 验收项 | 通过标准 |
|---|---|---|
| 1 | 前台未登录不可访问 | 任意页面 → `/login` |
| 2 | USER 不能访问管理端 | `/api/admin/**` → 403，管理端路由 → 拒绝 |
| 3 | 合同列表可见性隔离 | 三个部门各建合同，USER 只看到有权看的 |
| 4 | 合同详情/文档/run/报告全资源面隔离 | 直接 URL 调不可见合同 → 404 |
| 5 | SSE 流隔离 | 不可见合同的 run SSE → 404 |
| 6 | 修改 finding/element/timeline 隔离 | 不可见合同的修改被拒绝 |
| 7 | 前台 Header 显示部门 | 登录后顶部显示"法务部" |
| 8 | 合同创建自动填充字段 | creator_id/department_id 正确写入 |
| 9 | 额度两阶段 + 并发安全 | 分析成功扣, 失败退, SELECT FOR UPDATE |
| 10 | Refresh token 无感续期 | 30min 后自动 refresh |
| 11 | Refresh token rotation + 重放检测 | 重放旧 token → family 全撤销 |
| 12 | 管理员用户 CRUD + 额度调整 | 创建/编辑/禁用/调整额度均有流水 |
| 13 | 部门软删除 | 默认部门拒绝删除, 普通部门删除后用户迁默认 |
| 14 | 最后一个管理员保护 | 删除/降级最后 ADMIN 被拒绝 |
| 15 | 禁用用户即时生效 | 已登录用户被踢出 |
| 16 | Python fail-closed | 未配 token 或错误 token → 403/500 |
| 17 | Python 不暴露公网 | docker-compose 无 18088 端口映射 |
| 18 | 操作审计完整 | 所有管理员 CUD 操作有 `@OperationLog` 记录 |
