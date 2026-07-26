package com.atlasmind.service;

import com.atlasmind.config.EmbeddingConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

/**
 * Embedding 向量生成服务。
 * <p>
 * 调用 OpenAI 兼容 API 将文本转为语义向量，
 * 供 ES dense_vector kNN 语义搜索使用。
 * <p>
 * 未配置 apiKey 时自动禁用，所有方法返回空数组。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class EmbeddingService {

    private final EmbeddingConfig config;

    private final RestTemplate restTemplate = new RestTemplate();

    /** 单次输入最大字符数（ada-002: ~8191 tokens ≈ 32K chars，保守截断到 8000） */
    private static final int MAX_CHARS = 8000;

    /**
     * 是否已启用（apiKey 已配置）。
     */
    public boolean isEnabled() {
        return config.getApiKey() != null && !config.getApiKey().isBlank();
    }

    /**
     * 生成文本的 embedding 向量。
     *
     * @param text 输入文本（过长自动截断）
     * @return embedding provider 返回的 float 数组；未启用或失败时返回 {@code null}
     */
    public float[] embed(String text) {
        if (!isEnabled() || text == null || text.isBlank()) {
            return null;
        }

        String truncated = text.length() > MAX_CHARS ? text.substring(0, MAX_CHARS) : text;

        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.setBearerAuth(config.getApiKey());

            Map<String, Object> body = Map.of(
                    "model", config.getModel(),
                    "input", truncated
            );

            HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);
            ResponseEntity<Map> response = restTemplate.postForEntity(
                    config.getBaseUrl() + "/embeddings",
                    request,
                    Map.class
            );

            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                List<Map<String, Object>> data = (List<Map<String, Object>>) response.getBody().get("data");
                if (data != null && !data.isEmpty()) {
                    List<Double> embedding = (List<Double>) data.get(0).get("embedding");
                    if (embedding != null) {
                        float[] result = new float[embedding.size()];
                        for (int i = 0; i < embedding.size(); i++) {
                            result[i] = embedding.get(i).floatValue();
                        }
                        return result;
                    }
                }
            }
            log.warn("Embedding API returned unexpected response: status={}", response.getStatusCode());
        } catch (Exception e) {
            log.warn("Embedding API call failed: {}", e.getMessage());
        }
        return null;
    }

    /**
     * 拼接文章标题 + 摘要 + 正文作为 embedding 输入。
     */
    public String buildEmbeddingText(String title, String summary, String content) {
        StringBuilder sb = new StringBuilder();
        if (title != null) sb.append(title).append("\n");
        if (summary != null) sb.append(summary).append("\n");
        if (content != null) sb.append(content);
        return sb.toString();
    }
}
