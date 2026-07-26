package com.atlasmind.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.data.elasticsearch.client.ClientConfiguration;
import org.springframework.data.elasticsearch.client.elc.ElasticsearchConfiguration;

/**
 * Elasticsearch 客户端配置 — 仅在非 dev 环境激活。
 * <p>
 * 开发环境默认使用 MySQL LIKE 搜索，避免因缺少 ES 服务导致启动失败。
 * 需要 ES 时使用 {@code -Dspring.profiles.active=dev,es} 或切换 prod 环境。
 */
@Configuration
@Profile("!dev")
public class ElasticsearchConfig extends ElasticsearchConfiguration {

    @Override
    public ClientConfiguration clientConfiguration() {
        return ClientConfiguration.builder()
                .connectedTo("localhost:9200")
                .build();
    }
}
