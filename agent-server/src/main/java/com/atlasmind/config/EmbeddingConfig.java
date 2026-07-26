package com.atlasmind.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * Embedding 配置，映射 {@code atlasmind.embedding.*} 到本类。
 * <p>
 * 用于生成文章语义向量，配合 ES dense_vector kNN 搜索。
 * 未配置时（api-key 为空）EmbeddingService 自动禁用，降级为纯文本搜索。
 */
@Data
@Configuration
@ConfigurationProperties(prefix = "atlasmind.embedding")
public class EmbeddingConfig {

    /** OpenAI 兼容 API Key */
    private String apiKey = "";

    /** API Base URL（默认 OpenAI） */
    private String baseUrl = "https://api.openai.com/v1";

    /** Embedding 模型名 */
    private String model = "text-embedding-ada-002";
}
