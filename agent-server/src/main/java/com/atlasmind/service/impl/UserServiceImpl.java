package com.atlasmind.service.impl;

import cn.hutool.crypto.digest.BCrypt;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.Department;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.DepartmentMapper;
import com.atlasmind.mapper.UserMapper;
import com.atlasmind.service.UserService;
import lombok.RequiredArgsConstructor;
import com.atlasmind.annotation.CacheShieldEvict;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.UUID;

/**
 * 用户服务实现。
 * <p>
 * 密码使用 Hutool BCrypt 哈希，登录时校验哈希匹配。
 * {@code getById} 自动置空密码字段防止泄露。
 */
@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService {

    private final UserMapper userMapper;
    private final DepartmentMapper departmentMapper;
    private final JdbcTemplate jdbcTemplate;

    @Override
    public User login(String username, String password) {
        User user = userMapper.selectOne(new LambdaQueryWrapper<User>().eq(User::getUsername, username));
        if (user == null || !BCrypt.checkpw(password, user.getPassword())) {
            throw new IllegalArgumentException("用户名或密码错误");
        }
        if (!"ACTIVE".equals(user.getStatus())) {
            throw new IllegalStateException("账号已被禁用，请联系管理员");
        }
        user.setPassword(null);
        return user;
    }

    @Override
    public User getById(Long id) {
        User user = userMapper.selectById(id);
        if (user != null) {
            user.setPassword(null);
            if (user.getDepartmentId() != null) {
                Department dept = departmentMapper.selectById(user.getDepartmentId());
                if (dept != null) user.setDepartmentName(dept.getName());
            }
        }
        return user;
    }

    @Override
    public User getSiteInfo() {
        User user = userMapper.selectById(1L);
        if (user != null) user.setPassword(null);
        return user;
    }

    @Override
    public void updatePassword(Long userId, String oldPassword, String newPassword) {
        User user = userMapper.selectById(userId);
        if (user == null || !BCrypt.checkpw(oldPassword, user.getPassword())) {
            throw new IllegalArgumentException("旧密码错误");
        }
        user.setPassword(BCrypt.hashpw(newPassword));
        userMapper.updateById(user);
    }

    @CacheShieldEvict(value = "siteInfo", key = "'site'")
    @Override
    public void updateProfile(Long userId, String nickname, String email, String avatar, String bio, String socialLinks) {
        User user = userMapper.selectById(userId);
        if (user == null) throw new IllegalArgumentException("用户不存在");
        if (nickname != null) user.setNickname(nickname);
        if (email != null) user.setEmail(email);
        if (avatar != null) user.setAvatar(avatar);
        if (bio != null) user.setBio(bio);
        if (socialLinks != null) user.setSocialLinks(socialLinks);
        userMapper.updateById(user);
    }

    // ── Refresh token methods ──────────────────────────────────────

    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    @Override
    public void saveRefreshToken(Long userId, String tokenHash, String family) {
        jdbcTemplate.update(
            "INSERT INTO user_refresh_token (user_id, token_hash, family, expires_at) VALUES (?,?,?,?)",
            userId, tokenHash, family,
            LocalDateTime.now().plusDays(7));
    }

    @Override
    @Transactional
    public UserRefreshResult rotateRefreshToken(String tokenHash) {
        // SELECT FOR UPDATE to serialize concurrent refresh attempts
        var rows = jdbcTemplate.queryForList(
            "SELECT id, user_id, family, revoked, expires_at FROM user_refresh_token WHERE token_hash=? FOR UPDATE",
            tokenHash);
        if (rows.isEmpty()) {
            throw new IllegalArgumentException("无效的 refresh token");
        }
        var row = rows.get(0);
        int revoked = ((Number) row.get("revoked")).intValue();
        Long userId = ((Number) row.get("user_id")).longValue();
        String family = (String) row.get("family");

        if (revoked == 1) {
            // Token reuse detected → revoke entire family
            jdbcTemplate.update(
                "UPDATE user_refresh_token SET revoked=1, revoked_reason='REUSE_DETECTED' WHERE family=? AND revoked=0",
                family);
            throw new IllegalStateException("Refresh token 已被使用，出于安全考虑，该系列已全部作废，请重新登录");
        }

        // Check expiry
        LocalDateTime expiresAt = toLocalDateTime(row.get("expires_at"));
        if (expiresAt != null && expiresAt.isBefore(LocalDateTime.now())) {
            throw new IllegalArgumentException("Refresh token 已过期，请重新登录");
        }

        // Check user status
        User user = userMapper.selectById(userId);
        if (user == null || !"ACTIVE".equals(user.getStatus())) {
            throw new IllegalStateException("账号已被禁用");
        }

        // Revoke old token
        jdbcTemplate.update(
            "UPDATE user_refresh_token SET revoked=1, revoked_reason='ROTATION' WHERE token_hash=?",
            tokenHash);

        // Generate new token
        String newToken = generateRefreshToken();
        String newHash = sha256(newToken);
        jdbcTemplate.update(
            "INSERT INTO user_refresh_token (user_id, token_hash, family, expires_at) VALUES (?,?,?,?)",
            userId, newHash, family, LocalDateTime.now().plusDays(7));

        return new UserRefreshResult(userId, newToken);
    }

    @Override
    public void revokeRefreshToken(String tokenHash, String reason) {
        jdbcTemplate.update(
            "UPDATE user_refresh_token SET revoked=1, revoked_reason=? WHERE token_hash=?",
            reason, tokenHash);
    }

    @Override
    public void revokeAllRefreshTokens(Long userId) {
        jdbcTemplate.update(
            "UPDATE user_refresh_token SET revoked=1, revoked_reason='USER_DISABLED' WHERE user_id=? AND revoked=0",
            userId);
    }

    /** Generate a 256-bit random refresh token (64 hex chars). */
    public static String generateRefreshToken() {
        byte[] bytes = new byte[32];
        SECURE_RANDOM.nextBytes(bytes);
        return HexFormat.of().formatHex(bytes);
    }

    /** SHA-256 hash a token string into a 64-char hex digest. */
    public static String sha256(String input) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(input.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException e) {
            throw new RuntimeException("SHA-256 not available", e);
        }
    }

    private static LocalDateTime toLocalDateTime(Object value) {
        if (value == null) return null;
        if (value instanceof LocalDateTime localDateTime) return localDateTime;
        if (value instanceof Timestamp timestamp) return timestamp.toLocalDateTime();
        throw new IllegalStateException("Unsupported datetime value type: " + value.getClass().getName());
    }
}
