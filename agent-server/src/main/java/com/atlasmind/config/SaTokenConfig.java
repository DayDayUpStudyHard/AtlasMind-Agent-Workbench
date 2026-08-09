package com.atlasmind.config;

import cn.dev33.satoken.interceptor.SaInterceptor;
import cn.dev33.satoken.stp.StpUtil;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Sa-Token 权限拦截配置。
 * <p>
 * 前台接口（/api/workspace/**, /api/projects/**, /api/kb/**, /api/upload/**, /api/ai/**）：
 *   登录即可访问，登录入口和 refresh 端点放行。
 * 管理端接口（/api/admin/**）：
 *   需要 ADMIN 角色，login/refresh 放行。
 */
@Configuration
public class SaTokenConfig implements WebMvcConfigurer {

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // 前台接口：登录即可
        registry.addInterceptor(new SaInterceptor(handle -> StpUtil.checkLogin()))
                .addPathPatterns(
                        "/api/workspace/**",
                        "/api/projects/**",
                        "/api/kb/**",
                        "/api/upload/**",
                        "/api/ai/**")
                .excludePathPatterns(
                        "/api/auth/login",
                        "/api/auth/refresh");

        // 管理端接口：需要 ADMIN 角色
        registry.addInterceptor(new SaInterceptor(handle -> {
                    StpUtil.checkLogin();
                    StpUtil.checkRole("ADMIN");
                }))
                .addPathPatterns("/api/admin/**")
                .excludePathPatterns(
                        "/api/auth/login",
                        "/api/auth/refresh");
    }
}
