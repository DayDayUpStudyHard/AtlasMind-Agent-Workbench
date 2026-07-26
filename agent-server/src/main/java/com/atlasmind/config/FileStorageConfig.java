package com.atlasmind.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * 文件存储配置，映射 {@code atlasmind.storage.*} 到本类。
 * <p>
 * 通过 {@code atlasmind.storage.type} 决定使用本地存储还是 S3 兼容存储。
 * S3Config 内所有字段根据所选对象存储服务商配置（Cloudflare R2 / AWS S3 / MinIO 等）。
 */
@Data
@Configuration
@ConfigurationProperties(prefix = "atlasmind.storage")
public class FileStorageConfig {

    private String type = "local";

    private S3Config s3 = new S3Config();

    @Data
    public static class S3Config {
        private String endpoint;
        private String region = "auto";
        private String accessKey;
        private String secretKey;
        private String bucket;
        private String publicUrl;
    }
}
