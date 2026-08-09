package com.atlasmind.service.impl;

import cn.hutool.crypto.digest.BCrypt;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.UserMapper;
import com.atlasmind.service.UserService.UserRefreshResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * UserServiceImpl 单元测试 — 使用 Mockito 模拟 Mapper 和 JdbcTemplate。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("用户服务单元测试")
class UserServiceImplTest {

    @Mock
    private UserMapper userMapper;

    @Mock
    private JdbcTemplate jdbcTemplate;

    @InjectMocks
    private UserServiceImpl userService;

    private User mockUser;

    @BeforeEach
    void setUp() {
        mockUser = new User();
        mockUser.setId(1L);
        mockUser.setUsername("admin");
        mockUser.setPassword(BCrypt.hashpw("admin123"));
        mockUser.setNickname("管理员");
        mockUser.setEmail("admin@atlasmind.local");
        mockUser.setRole("ADMIN");
        mockUser.setStatus("ACTIVE");
    }

    // ── Existing tests (login / profile / password) ──────────────

    @Test
    @DisplayName("登录成功 — 正确的用户名和密码")
    void loginSuccess() {
        when(userMapper.selectOne(any())).thenReturn(mockUser);

        User result = userService.login("admin", "admin123");

        assertNotNull(result);
        assertEquals("admin", result.getUsername());
        assertNull(result.getPassword());
        verify(userMapper).selectOne(any());
    }

    @Test
    @DisplayName("登录失败 — 密码错误")
    void loginFailWrongPassword() {
        when(userMapper.selectOne(any())).thenReturn(mockUser);

        assertThrows(IllegalArgumentException.class, () ->
                userService.login("admin", "wrongpassword"));
    }

    @Test
    @DisplayName("登录失败 — 用户不存在")
    void loginFailUserNotFound() {
        when(userMapper.selectOne(any())).thenReturn(null);

        assertThrows(IllegalArgumentException.class, () ->
                userService.login("nobody", "password"));
    }

    @Test
    @DisplayName("获取用户信息 — 密码字段置空")
    void getByIdClearsPassword() {
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        User result = userService.getById(1L);

        assertNotNull(result);
        assertNull(result.getPassword());
        assertEquals("admin", result.getUsername());
    }

    @Test
    @DisplayName("修改密码 — 旧密码错误时抛异常")
    void updatePasswordWrongOldPassword() {
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        assertThrows(IllegalArgumentException.class, () ->
                userService.updatePassword(1L, "wrongold", "newpassword"));
    }

    @Test
    @DisplayName("修改密码 — 成功更新")
    void updatePasswordSuccess() {
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        assertDoesNotThrow(() ->
                userService.updatePassword(1L, "admin123", "newpassword"));
        verify(userMapper).updateById(any(User.class));
    }

    @Test
    @DisplayName("获取站点信息 — 取 id=1 用户")
    void getSiteInfo() {
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        User result = userService.getSiteInfo();

        assertNotNull(result);
        assertNull(result.getPassword());
        assertEquals("管理员", result.getNickname());
    }

    @Test
    @DisplayName("更新个人资料 — 用户不存在时抛异常")
    void updateProfileUserNotFound() {
        when(userMapper.selectById(999L)).thenReturn(null);

        assertThrows(IllegalArgumentException.class, () ->
                userService.updateProfile(999L, "name", "email@test.com", null, null, null));
    }

    @Test
    @DisplayName("更新个人资料 — 成功更新部分字段")
    void updateProfileSuccess() {
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        userService.updateProfile(1L, "新昵称", null, null, null, null);

        assertEquals("新昵称", mockUser.getNickname());
        assertEquals("admin@atlasmind.local", mockUser.getEmail());
        verify(userMapper).updateById(mockUser);
    }

    // ── Refresh token rotation tests ─────────────────────────────

    /** Helper: build a token row map for queryForList return. */
    private Map<String, Object> tokenRow(long id, long userId, String family, int revoked, LocalDateTime expiresAt) {
        Map<String, Object> row = new HashMap<>();
        row.put("id", id);
        row.put("user_id", userId);
        row.put("family", family);
        row.put("revoked", revoked);
        row.put("expires_at", expiresAt);
        return row;
    }

    private List<Map<String, Object>> tokenList(Map<String, Object> row) {
        List<Map<String, Object>> list = new ArrayList<>();
        list.add(row);
        return list;
    }

    @Test
    @DisplayName("Refresh Token 轮换 — 正常流程：旧 token 标记为 ROTATION，生成新 token")
    void rotateRefreshTokenSuccess() {
        String oldHash = UserServiceImpl.sha256("old-token-raw");
        String family = "test-family-001";

        // First call: SELECT FOR UPDATE returns a valid, non-revoked token
        Map<String, Object> tokenRow = tokenRow(10L, 1L, family, 0, LocalDateTime.now().plusDays(3));
        when(jdbcTemplate.queryForList(startsWith("SELECT id, user_id, family"), eq(oldHash)))
                .thenReturn(tokenList(tokenRow));

        // User status check
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        // UPDATE (revoke old) and INSERT (new token) — return 1 row affected
        when(jdbcTemplate.update(startsWith("UPDATE user_refresh_token SET revoked=1"), eq(oldHash)))
                .thenReturn(1);
        when(jdbcTemplate.update(startsWith("INSERT INTO user_refresh_token"), anyLong(), anyString(), eq(family), any()))
                .thenReturn(1);

        UserRefreshResult result = userService.rotateRefreshToken(oldHash);

        assertNotNull(result);
        assertEquals(1L, result.userId());
        assertNotNull(result.newToken());
        assertNotEquals("old-token-raw", result.newToken());

        // Verify old token was revoked with ROTATION reason
        verify(jdbcTemplate).update(startsWith("UPDATE user_refresh_token SET revoked=1"), eq(oldHash));
        // Verify new token was inserted
        verify(jdbcTemplate).update(startsWith("INSERT INTO user_refresh_token"), eq(1L), anyString(), eq(family), any());
    }

    @Test
    @DisplayName("Refresh Token 重放检测 — 已 revoke 的 token 再次使用 → 整族作废")
    void rotateRefreshTokenReplayDetection() {
        String oldHash = UserServiceImpl.sha256("stolen-token");
        String family = "test-family-002";

        // SELECT FOR UPDATE returns a token that's already revoked (token theft replay)
        Map<String, Object> revokedRow = tokenRow(20L, 1L, family, 1, LocalDateTime.now().plusDays(3));
        when(jdbcTemplate.queryForList(startsWith("SELECT id, user_id, family"), eq(oldHash)))
                .thenReturn(tokenList(revokedRow));

        // Family-wide revocation UPDATE
        when(jdbcTemplate.update(startsWith("UPDATE user_refresh_token SET revoked=1, revoked_reason='REUSE_DETECTED'"), eq(family)))
                .thenReturn(2);

        IllegalStateException ex = assertThrows(IllegalStateException.class, () ->
                userService.rotateRefreshToken(oldHash));

        assertTrue(ex.getMessage().contains("作废") || ex.getMessage().contains("reuse"),
                "Expected message about token reuse/family revocation, got: " + ex.getMessage());

        // Verify entire family was revoked
        verify(jdbcTemplate).update(startsWith("UPDATE user_refresh_token SET revoked=1, revoked_reason='REUSE_DETECTED'"), eq(family));
    }

    @Test
    @DisplayName("Refresh Token 轮换 — token 过期时抛异常")
    void rotateRefreshTokenExpired() {
        String oldHash = UserServiceImpl.sha256("expired-token");
        String family = "test-family-003";

        // SELECT FOR UPDATE returns an expired token
        Map<String, Object> expiredRow = tokenRow(30L, 1L, family, 0, LocalDateTime.now().minusDays(1));
        when(jdbcTemplate.queryForList(startsWith("SELECT id, user_id, family"), eq(oldHash)))
                .thenReturn(tokenList(expiredRow));

        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () ->
                userService.rotateRefreshToken(oldHash));

        assertTrue(ex.getMessage().contains("过期") || ex.getMessage().contains("expired"),
                "Expected message about token expiry, got: " + ex.getMessage());
    }

    @Test
    @DisplayName("Refresh Token 轮换 — 账号被禁用时抛异常")
    void rotateRefreshTokenUserDisabled() {
        String oldHash = UserServiceImpl.sha256("disabled-user-token");
        String family = "test-family-004";

        // Valid non-expired token
        Map<String, Object> tokenRow = tokenRow(40L, 2L, family, 0, LocalDateTime.now().plusDays(3));
        when(jdbcTemplate.queryForList(startsWith("SELECT id, user_id, family"), eq(oldHash)))
                .thenReturn(tokenList(tokenRow));

        // User is DISABLED
        User disabledUser = new User();
        disabledUser.setId(2L);
        disabledUser.setRole("USER");
        disabledUser.setStatus("DISABLED");
        when(userMapper.selectById(2L)).thenReturn(disabledUser);

        IllegalStateException ex = assertThrows(IllegalStateException.class, () ->
                userService.rotateRefreshToken(oldHash));

        assertTrue(ex.getMessage().contains("禁用") || ex.getMessage().contains("disabled"),
                "Expected message about disabled account, got: " + ex.getMessage());
    }

    @Test
    @DisplayName("Refresh Token 轮换 — 不存在的 token 抛异常")
    void rotateRefreshTokenNotFound() {
        String unknownHash = UserServiceImpl.sha256("nonexistent-token");

        // SELECT FOR UPDATE returns empty list
        when(jdbcTemplate.queryForList(startsWith("SELECT id, user_id, family"), eq(unknownHash)))
                .thenReturn(new ArrayList<>());

        assertThrows(IllegalArgumentException.class, () ->
                userService.rotateRefreshToken(unknownHash));
    }

    @Test
    @DisplayName("并发双 refresh 串行化后 — 第二个请求检测到 token 已被轮换，触发重放保护")
    void concurrentDoubleRefreshDetectsReplay() throws Exception {
        String tokenHash = UserServiceImpl.sha256("concurrent-token");
        String family = "test-family-concurrent";

        // Thread 1: sees valid token → succeeds
        Map<String, Object> validRow = tokenRow(50L, 1L, family, 0, LocalDateTime.now().plusDays(3));
        // Thread 2: sees the already-revoked token → REUSE_DETECTED
        Map<String, Object> revokedRow = tokenRow(50L, 1L, family, 1, LocalDateTime.now().plusDays(3));

        // First call to queryForList returns valid; second returns revoked (simulating concurrent access)
        when(jdbcTemplate.queryForList(startsWith("SELECT id, user_id, family"), eq(tokenHash)))
                .thenReturn(tokenList(validRow))     // Thread 1
                .thenReturn(tokenList(revokedRow));  // Thread 2

        when(userMapper.selectById(1L)).thenReturn(mockUser);
        when(jdbcTemplate.update(startsWith("UPDATE user_refresh_token SET revoked=1"), eq(tokenHash)))
                .thenReturn(1);
        when(jdbcTemplate.update(startsWith("UPDATE user_refresh_token SET revoked=1, revoked_reason='REUSE_DETECTED'"), eq(family)))
                .thenReturn(1);
        when(jdbcTemplate.update(startsWith("INSERT INTO user_refresh_token"), anyLong(), anyString(), eq(family), any()))
                .thenReturn(1);

        UserRefreshResult result1 = userService.rotateRefreshToken(tokenHash);
        assertNotNull(result1, "First refresh should successfully rotate the token");
        assertEquals(1L, result1.userId());

        IllegalStateException replay = assertThrows(IllegalStateException.class,
                () -> userService.rotateRefreshToken(tokenHash));
        assertTrue(replay.getMessage().contains("作废") || replay.getMessage().contains("已被使用"),
                "Expected message about replay/family revocation, got: " + replay.getMessage());

        // Verify family was revoked due to reuse detection
        verify(jdbcTemplate).update(startsWith("UPDATE user_refresh_token SET revoked=1, revoked_reason='REUSE_DETECTED'"), eq(family));
    }

    @Test
    @DisplayName("revokeRefreshToken — 按 hash 撤销单个 token")
    void revokeRefreshTokenByHash() {
        String tokenHash = UserServiceImpl.sha256("token-to-revoke");
        when(jdbcTemplate.update(anyString(), eq("LOGOUT"), eq(tokenHash))).thenReturn(1);

        userService.revokeRefreshToken(tokenHash, "LOGOUT");

        verify(jdbcTemplate).update(contains("SET revoked=1"), eq("LOGOUT"), eq(tokenHash));
    }

    @Test
    @DisplayName("revokeAllRefreshTokens — 撤销用户所有活跃 token，标记 USER_DISABLED")
    void revokeAllRefreshTokensForUser() {
        when(jdbcTemplate.update(contains("SET revoked=1"), eq(1L))).thenReturn(3);

        userService.revokeAllRefreshTokens(1L);

        verify(jdbcTemplate).update(contains("revoked_reason='USER_DISABLED'"), eq(1L));
    }
}
