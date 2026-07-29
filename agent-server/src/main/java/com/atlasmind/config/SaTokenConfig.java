package com.atlasmind.config;

import cn.dev33.satoken.interceptor.SaInterceptor;
import cn.dev33.satoken.stp.StpUtil;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Sa-Token 权限拦截配置。
 * <p>
 * 拦截所有 {@code /api/admin/**} 请求并校验登录态；{@code /api/auth/login} 作为登录入口放行。
 * 路由匹配在拦截器层面生效，Controller 内部无需重复校验。
 */
@Configuration
public class SaTokenConfig implements WebMvcConfigurer {

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new SaInterceptor(handle -> StpUtil.checkLogin()))
                .addPathPatterns(
                        "/api/admin/**",
                        "/api/workspace/**",
                        "/api/projects/**",
                        "/api/kb/**",
                        "/api/upload/**")
                .excludePathPatterns("/api/auth/login");
    }
}
