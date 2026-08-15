package com.atlasmind.config;

import cn.dev33.satoken.interceptor.SaInterceptor;
import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
import org.springframework.web.server.ResponseStatusException;

/**
 * Sa-Token 权限拦截配置。
 * <p>
 * 前台接口（/api/workspace/**, /api/projects/**, /api/kb/**, /api/upload/**, /api/ai/**）：
 *   登录即可访问，登录入口和 refresh 端点放行。
 * 管理端接口（/api/admin/**）：
 *   需要 ADMIN 角色，login/refresh 放行。
 */
@Configuration
@RequiredArgsConstructor
public class SaTokenConfig implements WebMvcConfigurer {

    private final UserMapper userMapper;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // 前台接口：登录即可
        registry.addInterceptor(new SaInterceptor(handle -> checkActiveLogin()))
                .addPathPatterns(
                        "/api/auth/**",
                        "/api/workspace/**",
                        "/api/projects/**",
                        "/api/kb/**",
                        "/api/upload/**",
                        "/api/ai/**",
                        "/api/chat/**",
                        "/upload/**")
                .excludePathPatterns(
                        "/api/auth/login",
                        "/api/auth/refresh",
                        "/api/auth/logout",
                        "/api/internal/**");   // 内部端点走 service token

        // 管理端接口：需要 ADMIN 角色
        registry.addInterceptor(new SaInterceptor(handle -> {
                    checkActiveLogin();
                    StpUtil.checkRole("ADMIN");
                }))
                .addPathPatterns("/api/admin/**")
                .excludePathPatterns(
                        "/api/auth/login",
                        "/api/auth/refresh");
    }

    private void checkActiveLogin() {
        StpUtil.checkLogin();
        long userId = StpUtil.getLoginIdAsLong();
        User user = userMapper.selectById(userId);
        if (user == null || !"ACTIVE".equals(user.getStatus())) {
            StpUtil.logout();
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "账号已被禁用");
        }
    }
}
