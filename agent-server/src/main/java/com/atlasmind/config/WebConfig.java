package com.atlasmind.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * 静态资源映射，将上传目录映射为 HTTP 可访问路径。
 * <p>
 * {@code /upload/**} → {@code file:upload/}，上传后的文件可直接通过 URL 访问。
 * 生产环境建议使用 Nginx 代理静态文件或接入 CDN / S3。
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        registry.addResourceHandler("/upload/**")
                .addResourceLocations("file:upload/");
    }
}
