package com.atlasmind.gateway;

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
 * Minimal GitHub Issue connector — used by ContractOps approval actions.
 */
@Component
@RequiredArgsConstructor
public class HttpGitHubIssueGateway implements GitHubIssueGateway {

    private final ObjectMapper objectMapper;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(3)).build();

    @Value("${atlasmind.github.token:}")
    private String token;

    @Override
    public Map<String, Object> createIssue(String repositoryUrl, String title, String body) {
        if (token == null || token.isBlank())
            throw new IllegalStateException("GitHub token not configured");
        String[] repo = parseRepo(repositoryUrl);
        try {
            String payload = objectMapper.writeValueAsString(Map.of("title", title, "body", body));
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create("https://api.github.com/repos/" + repo[0] + "/" + repo[1] + "/issues"))
                    .timeout(Duration.ofSeconds(15))
                    .header("Accept", "application/vnd.github+json")
                    .header("Authorization", "Bearer " + token)
                    .header("X-GitHub-Api-Version", "2022-11-28")
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(payload)).build();
            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400)
                throw new IllegalStateException("GitHub Issue failed: HTTP " + resp.statusCode());
            return objectMapper.readValue(resp.body(), new com.fasterxml.jackson.core.type.TypeReference<>() {});
        } catch (Exception e) { throw new IllegalStateException(e.getMessage(), e); }
    }

    @Override
    public Map<String, Object> createMilestone(String repositoryUrl, String title, String description, String dueOn) {
        if (token == null || token.isBlank())
            throw new IllegalStateException("GitHub token not configured");
        String[] repo = parseRepo(repositoryUrl);
        try {
            Map<String, Object> body = new java.util.HashMap<>();
            body.put("title", title);
            body.put("description", description == null ? "" : description);
            if (dueOn != null && !dueOn.isBlank()) body.put("due_on", dueOn + "T00:00:00Z");
            String payload = objectMapper.writeValueAsString(body);
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create("https://api.github.com/repos/" + repo[0] + "/" + repo[1] + "/milestones"))
                    .timeout(Duration.ofSeconds(15))
                    .header("Accept", "application/vnd.github+json")
                    .header("Authorization", "Bearer " + token)
                    .header("X-GitHub-Api-Version", "2022-11-28")
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(payload)).build();
            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400)
                throw new IllegalStateException("GitHub Milestone failed: HTTP " + resp.statusCode());
            return objectMapper.readValue(resp.body(), new com.fasterxml.jackson.core.type.TypeReference<>() {});
        } catch (Exception e) { throw new IllegalStateException(e.getMessage(), e); }
    }

    private String[] parseRepo(String url) {
        if (url == null || url.isBlank()) throw new IllegalArgumentException("Repository URL required");
        String clean = url.replaceAll("/+$", "").replace(".git", "");
        int m = clean.indexOf("github.com/");
        if (m < 0) throw new IllegalArgumentException("Only github.com supported");
        String[] parts = clean.substring(m + "github.com/".length()).split("/");
        if (parts.length < 2) throw new IllegalArgumentException("Invalid repo URL");
        return new String[]{parts[0], parts[1]};
    }
}
