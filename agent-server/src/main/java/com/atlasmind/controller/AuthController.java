package com.atlasmind.controller;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.annotation.RateLimit;
import com.atlasmind.common.Result;
import com.atlasmind.dto.LoginDto;
import com.atlasmind.dto.PasswordDto;
import com.atlasmind.entity.User;
import com.atlasmind.service.UserService;
import com.atlasmind.service.UserService.UserRefreshResult;
import com.atlasmind.service.impl.UserServiceImpl;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * 认证接口：登录、刷新令牌、登出、获取当前用户信息、修改密码和个人资料。
 * <p>
 * 登录成功后通过 {@code StpUtil.login(userId)} 写入 Sa-Token 会话，
 * 同时生成 httpOnly Refresh Token Cookie（7天有效期）。
 * 后续请求由 {@code SaTokenConfig} 中的拦截器自动校验。
 * 密码使用 BCrypt 加密。
 */
@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/auth")
public class AuthController {

    private final UserService userService;

    @RateLimit(key = "login", limit = 5, window = 60, message = "登录过于频繁，请 1 分钟后再试")
    @PostMapping("/login")
    public Result<Map<String, Object>> login(@Valid @RequestBody LoginDto dto,
                                              HttpServletResponse response) {
        User user = userService.login(dto.getUsername(), dto.getPassword());

        StpUtil.login(user.getId());

        // 生成 Refresh Token
        String refreshToken = UserServiceImpl.generateRefreshToken();
        String tokenHash = UserServiceImpl.sha256(refreshToken);
        String family = UUID.randomUUID().toString();
        userService.saveRefreshToken(user.getId(), tokenHash, family);

        // 使用 ResponseCookie 保证 SameSite 在所有 Servlet 容器版本都可靠
        ResponseCookie cookie = ResponseCookie.from("refresh_token", refreshToken)
                .httpOnly(true)
                .secure(false)   // 生产环境需 HTTPS 并改为 true
                .path("/api")
                .maxAge(Duration.ofDays(7))
                .sameSite("Lax")
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());

        String accessToken = StpUtil.getTokenValue();
        log.info("用户 {} (id={}) 登录成功", user.getUsername(), user.getId());

        Map<String, Object> map = new HashMap<>();
        map.put("token", accessToken);
        map.put("user", user);
        return Result.ok(map);
    }

    @PostMapping("/refresh")
    public Result<Map<String, Object>> refresh(
            @CookieValue(value = "refresh_token", required = false) String refreshToken,
            HttpServletResponse response) {
        if (refreshToken == null || refreshToken.isBlank()) {
            log.warn("Refresh 请求缺少 refresh_token cookie");
            throw new IllegalArgumentException("缺少 refresh token，请重新登录");
        }
        String tokenHash = UserServiceImpl.sha256(refreshToken);

        // 事务内完成 find → revoke → save
        UserRefreshResult result = userService.rotateRefreshToken(tokenHash);

        // 新 Sa-Token access token
        StpUtil.login(result.userId());
        String newAccessToken = StpUtil.getTokenValue();

        // 更新 Cookie（使用 ResponseCookie 保证 SameSite 可靠）
        ResponseCookie cookie = ResponseCookie.from("refresh_token", result.newToken())
                .httpOnly(true)
                .secure(false)
                .path("/api")
                .maxAge(Duration.ofDays(7))
                .sameSite("Lax")
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());

        log.debug("用户 {} refresh token 轮换成功", result.userId());
        return Result.ok(Map.of("token", newAccessToken));
    }

    @PostMapping("/logout")
    public Result<?> logout(
            @CookieValue(value = "refresh_token", required = false) String refreshToken,
            HttpServletResponse response) {
        if (refreshToken != null && !refreshToken.isBlank()) {
            userService.revokeRefreshToken(UserServiceImpl.sha256(refreshToken), "LOGOUT");
        }
        StpUtil.logout();

        // 清除 Cookie
        ResponseCookie cookie = ResponseCookie.from("refresh_token", "")
                .httpOnly(true)
                .path("/api")
                .maxAge(0)
                .sameSite("Lax")
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());

        return Result.ok();
    }

    @GetMapping("/info")
    public Result<User> info() {
        long userId = StpUtil.getLoginIdAsLong();
        return Result.ok(userService.getById(userId));
    }

    @PutMapping("/password")
    public Result<?> updatePassword(@Valid @RequestBody PasswordDto dto) {
        long userId = StpUtil.getLoginIdAsLong();
        userService.updatePassword(userId, dto.getOldPassword(), dto.getNewPassword());
        return Result.ok();
    }

    @PutMapping("/profile")
    public Result<?> updateProfile(@Valid @RequestBody User user) {
        long userId = StpUtil.getLoginIdAsLong();
        userService.updateProfile(userId, user.getNickname(), user.getEmail(), user.getAvatar(), user.getBio(), user.getSocialLinks());
        return Result.ok();
    }
}
