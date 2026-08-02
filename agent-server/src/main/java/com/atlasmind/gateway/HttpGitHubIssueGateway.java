package com.atlasmind.gateway;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

/**
 * 受配置保护的 GitHub Issue connector。
 */
@Component
@RequiredArgsConstructor
public class HttpGitHubIssueGateway implements GitHubIssueGateway {

    private final ObjectMapper objectMapper;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(3))
            .build();

    @Value("${atlasmind.github.token:}")
    private String token;

    @Override
    public Map<String, Object> createIssue(String repositoryUrl, String title, String body) {
        if (token == null || token.isBlank()) {
            throw new IllegalStateException("GitHub App token 未配置，Issue 仅生成了待审批草稿");
        }
        String[] repository = parseRepository(repositoryUrl);
        try {
            String payload = objectMapper.writeValueAsString(Map.of("title", title, "body", body));
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("https://api.github.com/repos/" + repository[0] + "/" + repository[1] + "/issues"))
                    .timeout(Duration.ofSeconds(15))
                    .header("Accept", "application/vnd.github+json")
                    .header("Authorization", "Bearer " + token)
                    .header("X-GitHub-Api-Version", "2022-11-28")
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(payload))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() >= 400) {
                throw new IllegalStateException("GitHub Issue 创建失败: HTTP " + response.statusCode());
            }
            return objectMapper.readValue(response.body(), new TypeReference<>() {});
        } catch (Exception e) {
            throw new IllegalStateException(e.getMessage(), e);
        }
    }

    @Override
    public Map<String, Object> createMilestone(String repositoryUrl, String title,
                                                String description, String dueOn) {
        if (token == null || token.isBlank()) {
            throw new IllegalStateException("GitHub App token 未配置");
        }
        String[] repository = parseRepository(repositoryUrl);
        try {
            Map<String, Object> body = new java.util.HashMap<>();
            body.put("title", title);
            body.put("description", description == null ? "" : description);
            if (dueOn != null && !dueOn.isBlank()) {
                // GitHub expects ISO 8601: YYYY-MM-DDTHH:MM:SSZ
                body.put("due_on", dueOn + "T00:00:00Z");
            }
            String payload = objectMapper.writeValueAsString(body);
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("https://api.github.com/repos/" + repository[0]
                            + "/" + repository[1] + "/milestones"))
                    .timeout(Duration.ofSeconds(15))
                    .header("Accept", "application/vnd.github+json")
                    .header("Authorization", "Bearer " + token)
                    .header("X-GitHub-Api-Version", "2022-11-28")
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(payload))
                    .build();
            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() >= 400) {
                throw new IllegalStateException(
                        "GitHub Milestone 创建失败: HTTP " + response.statusCode());
            }
            return objectMapper.readValue(response.body(), new TypeReference<>() {});
        } catch (Exception e) {
            throw new IllegalStateException(e.getMessage(), e);
        }
    }

    private String[] parseRepository(String repositoryUrl) {
        if (repositoryUrl == null || repositoryUrl.isBlank()) {
            throw new IllegalArgumentException("项目尚未绑定 GitHub 仓库");
        }
        String clean = repositoryUrl.replaceAll("/+$", "").replace(".git", "");
        int marker = clean.indexOf("github.com/");
        if (marker < 0) {
            throw new IllegalArgumentException("当前 Issue connector 只支持 github.com 仓库地址");
        }
        String path = clean.substring(marker + "github.com/".length());
        String[] parts = path.split("/");
        if (parts.length < 2 || parts[0].isBlank() || parts[1].isBlank()) {
            throw new IllegalArgumentException("GitHub 仓库地址格式不正确");
        }
        return new String[]{parts[0], parts[1]};
    }
}
