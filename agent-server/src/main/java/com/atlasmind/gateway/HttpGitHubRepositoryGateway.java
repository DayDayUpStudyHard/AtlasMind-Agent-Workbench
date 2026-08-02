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
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal read-only GitHub API client. Public repositories work without a token;
 * private/internal repositories use atlasmind.github.token when configured.
 */
@Component
@RequiredArgsConstructor
public class HttpGitHubRepositoryGateway implements GitHubRepositoryGateway {

    private static final int SNIPPET_LIMIT = 1800;

    private final ObjectMapper objectMapper;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    @Value("${atlasmind.github.token:}")
    private String token;

    @Override
    public List<Map<String, Object>> collectEvidence(String repositoryUrl, String branch) {
        String[] repository = parseRepository(repositoryUrl);
        String owner = repository[0];
        String repo = repository[1];
        String ref = branch == null || branch.isBlank() ? "main" : branch;
        List<Map<String, Object>> evidence = new ArrayList<>();

        Map<String, Object> repoMeta = getMap("/repos/" + owner + "/" + repo);
        evidence.add(evidence("REPO", text(repoMeta, "full_name"), text(repoMeta, "html_url"),
                owner + "/" + repo,
                "Default branch: " + value(repoMeta, "default_branch", ref)
                        + "\nLanguage: " + text(repoMeta, "language")
                        + "\nOpen issues: " + text(repoMeta, "open_issues_count")
                        + "\nDescription: " + text(repoMeta, "description"),
                repoMeta));
        ref = value(repoMeta, "default_branch", ref);

        addReadme(owner, repo, ref, evidence);
        addRootFiles(owner, repo, ref, evidence);
        addSourceCode(owner, repo, ref, evidence);
        addCommits(owner, repo, ref, evidence);
        addIssues(owner, repo, evidence);
        addPullRequests(owner, repo, evidence);
        return evidence;
    }

    private void addReadme(String owner, String repo, String ref, List<Map<String, Object>> evidence) {
        try {
            Map<String, Object> readme = getMap("/repos/" + owner + "/" + repo + "/readme?ref=" + ref);
            String content = decodeContent(text(readme, "content"));
            evidence.add(evidence("README", value(readme, "name", "README"), text(readme, "html_url"),
                    text(readme, "path"), content, readme));
        } catch (Exception ignored) {
            // Some repositories do not expose a README on the selected branch.
        }
    }

    // ── Source code collection (recursive, depth-limited) ──────────────

    private static final List<String> SOURCE_DIRS = List.of("src", "app", "lib", "agent-server/src",
            "tools", "agent-front/src");
    private static final List<String> SOURCE_EXTENSIONS = List.of(
            ".java", ".py", ".js", ".ts", ".vue", ".jsx", ".tsx", ".sql", ".yml", ".yaml",
            ".xml", ".json", ".css", ".scss", ".html", ".md", ".sh", ".dockerfile");
    private static final int SOURCE_MAX_FILES = 50;
    private static final int SOURCE_MAX_DEPTH = 4;
    private static final int SOURCE_SNIPPET_CHARS = 3000;

    private void addSourceCode(String owner, String repo, String ref, List<Map<String, Object>> evidence) {
        int collected = 0;
        for (String dir : SOURCE_DIRS) {
            if (collected >= SOURCE_MAX_FILES) break;
            collected += collectSourceDir(owner, repo, ref, dir, 0, evidence, collected);
        }
    }

    private int collectSourceDir(String owner, String repo, String ref, String path,
                                  int depth, List<Map<String, Object>> evidence, int collected) {
        if (depth > SOURCE_MAX_DEPTH || collected >= SOURCE_MAX_FILES) return 0;
        int added = 0;
        try {
            List<Map<String, Object>> contents = getList(
                    "/repos/" + owner + "/" + repo + "/contents/" + path + "?ref=" + ref);
            for (Map<String, Object> item : contents) {
                if (collected + added >= SOURCE_MAX_FILES) break;
                String type = text(item, "type");
                String itemPath = text(item, "path");
                if ("file".equals(type) && isSourceFile(itemPath)) {
                    addFile(owner, repo, ref, itemPath, evidence);
                    added++;
                } else if ("dir".equals(type) && !isSkippedDir(itemPath)) {
                    added += collectSourceDir(owner, repo, ref, itemPath, depth + 1,
                            evidence, collected + added);
                }
            }
        } catch (Exception ignored) {
            // Directory may not exist in this repo — skip silently.
        }
        return added;
    }

    private boolean isSourceFile(String path) {
        String lower = path.toLowerCase();
        for (String ext : SOURCE_EXTENSIONS) {
            if (lower.endsWith(ext)) return true;
        }
        return false;
    }

    private boolean isSkippedDir(String path) {
        String name = path.contains("/") ? path.substring(path.lastIndexOf('/') + 1) : path;
        return name.startsWith(".") || name.equals("node_modules")
                || name.equals("target") || name.equals("dist")
                || name.equals("build") || name.equals("__pycache__")
                || name.equals(".git") || name.equals("vendor");
    }

    /** Read a single file's full content from GitHub (on-demand, not synced). */
    public Map<String, Object> readFileContent(String repositoryUrl, String branch, String filePath) {
        String[] repo = parseRepository(repositoryUrl);
        String ref = branch == null || branch.isBlank() ? "main" : branch;
        try {
            Map<String, Object> file = getMap("/repos/" + repo[0] + "/" + repo[1]
                    + "/contents/" + filePath + "?ref=" + ref);
            String content = decodeContent(text(file, "content"));
            return Map.of("path", filePath, "content", content,
                    "size", text(file, "size"), "url", text(file, "html_url"));
        } catch (Exception e) {
            return Map.of("path", filePath, "error", e.getMessage());
        }
    }

    /** Search code in a GitHub repository using the GitHub Search API. */
    public List<Map<String, Object>> searchCode(String repositoryUrl, String query, int limit) {
        String[] repo = parseRepository(repositoryUrl);
        try {
            List<Map<String, Object>> items = getList("/search/code?q="
                    + java.net.URLEncoder.encode(query, StandardCharsets.UTF_8)
                    + "+repo:" + repo[0] + "/" + repo[1]
                    + "&per_page=" + Math.min(limit, 10));
            List<Map<String, Object>> results = new ArrayList<>();
            for (Map<String, Object> item : items) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("path", text(item, "path"));
                entry.put("name", text(item, "name"));
                entry.put("url", text(item, "html_url"));
                entry.put("gitUrl", text(item, "git_url"));
                Map<String, Object> repoInfo = mapValue(item.get("repository"));
                entry.put("repo", text(repoInfo, "full_name"));
                results.add(entry);
                if (results.size() >= limit) break;
            }
            return results;
        } catch (Exception e) {
            return List.of(Map.of("error", e.getMessage()));
        }
    }

    private void addRootFiles(String owner, String repo, String ref, List<Map<String, Object>> evidence) {
        try {
            List<Map<String, Object>> contents = getList("/repos/" + owner + "/" + repo + "/contents?ref=" + ref);
            StringBuilder tree = new StringBuilder();
            for (Map<String, Object> item : contents) {
                tree.append(text(item, "type")).append("  ").append(text(item, "path")).append("\n");
            }
            evidence.add(evidence("FILE_TREE", "Root file tree", "https://github.com/" + owner + "/" + repo + "/tree/" + ref,
                    "/", tree.toString(), Map.of("items", contents)));

            for (Map<String, Object> item : contents) {
                String type = text(item, "type");
                String path = text(item, "path");
                if ("file".equals(type) && isImportantRootFile(path)) {
                    addFile(owner, repo, ref, path, evidence);
                }
            }
        } catch (Exception ignored) {
            // File tree evidence is helpful but not mandatory for a run.
        }
    }

    private void addFile(String owner, String repo, String ref, String path, List<Map<String, Object>> evidence) {
        try {
            Map<String, Object> file = getMap("/repos/" + owner + "/" + repo + "/contents/" + path + "?ref=" + ref);
            String content = decodeContent(text(file, "content"));
            evidence.add(evidence("FILE", path, text(file, "html_url"), path, content, file));
        } catch (Exception ignored) {
            // Skip files that are too large or unavailable.
        }
    }

    private void addCommits(String owner, String repo, String ref, List<Map<String, Object>> evidence) {
        try {
            List<Map<String, Object>> commits = getList("/repos/" + owner + "/" + repo + "/commits?sha=" + ref + "&per_page=10");
            for (Map<String, Object> item : commits) {
                Map<String, Object> commit = mapValue(item.get("commit"));
                String message = firstLine(text(commit, "message"));
                Map<String, Object> author = mapValue(commit.get("author"));
                evidence.add(evidence("COMMIT", message, text(item, "html_url"), text(item, "sha"),
                        "Commit: " + message + "\nAuthor: " + text(author, "name") + "\nDate: " + text(author, "date"),
                        item));
            }
        } catch (Exception ignored) {
            // Commit evidence can be added later by another connector.
        }
    }

    private void addIssues(String owner, String repo, List<Map<String, Object>> evidence) {
        try {
            List<Map<String, Object>> issues = getList("/repos/" + owner + "/" + repo + "/issues?state=open&per_page=20");
            for (Map<String, Object> issue : issues) {
                if (issue.containsKey("pull_request")) {
                    continue;
                }
                evidence.add(evidence("ISSUE", "#" + text(issue, "number") + " " + text(issue, "title"),
                        text(issue, "html_url"), "#" + text(issue, "number"),
                        "State: " + text(issue, "state") + "\nTitle: " + text(issue, "title") + "\n" + text(issue, "body"),
                        issue));
            }
        } catch (Exception ignored) {
            // Issue evidence is optional for public read-only sync.
        }
    }

    private void addPullRequests(String owner, String repo, List<Map<String, Object>> evidence) {
        try {
            List<Map<String, Object>> pulls = getList("/repos/" + owner + "/" + repo + "/pulls?state=open&per_page=20");
            for (Map<String, Object> pull : pulls) {
                evidence.add(evidence("PR", "#" + text(pull, "number") + " " + text(pull, "title"),
                        text(pull, "html_url"), "#" + text(pull, "number"),
                        "State: " + text(pull, "state") + "\nTitle: " + text(pull, "title") + "\n" + text(pull, "body"),
                        pull));
            }
        } catch (Exception ignored) {
            // PR evidence is optional for public read-only sync.
        }
    }

    private Map<String, Object> evidence(String objectType, String title, String url, String ref,
                                         String snippet, Object raw) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("objectType", objectType);
        item.put("title", trim(title, 220));
        item.put("sourceUrl", url);
        item.put("sourceRef", ref);
        item.put("snippet", trim(snippet, SNIPPET_LIMIT));
        item.put("raw", raw);
        item.put("confidenceScore", confidence(objectType));
        return item;
    }

    private double confidence(String objectType) {
        return switch (objectType) {
            case "README", "FILE", "ISSUE", "PR" -> 0.92;
            case "COMMIT", "FILE_TREE" -> 0.86;
            default -> 0.8;
        };
    }

    private Map<String, Object> getMap(String pathAndQuery) {
        try {
            return objectMapper.readValue(send(pathAndQuery), new TypeReference<>() {});
        } catch (Exception e) {
            throw new IllegalStateException(e.getMessage(), e);
        }
    }

    private List<Map<String, Object>> getList(String pathAndQuery) {
        try {
            return objectMapper.readValue(send(pathAndQuery), new TypeReference<>() {});
        } catch (Exception e) {
            throw new IllegalStateException(e.getMessage(), e);
        }
    }

    private String send(String pathAndQuery) throws Exception {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create("https://api.github.com" + pathAndQuery))
                .timeout(Duration.ofSeconds(15))
                .header("Accept", "application/vnd.github+json")
                .header("X-GitHub-Api-Version", "2022-11-28")
                .GET();
        if (token != null && !token.isBlank()) {
            builder.header("Authorization", "Bearer " + token);
        }
        HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() >= 400) {
            throw new IllegalStateException("GitHub read failed: HTTP " + response.statusCode());
        }
        return response.body();
    }

    private String[] parseRepository(String repositoryUrl) {
        if (repositoryUrl == null || repositoryUrl.isBlank()) {
            throw new IllegalArgumentException("Project repository URL is required");
        }
        String clean = repositoryUrl.replaceAll("/+$", "").replace(".git", "");
        int marker = clean.indexOf("github.com/");
        if (marker < 0) {
            throw new IllegalArgumentException("Only github.com repository URLs are supported in this connector");
        }
        String path = clean.substring(marker + "github.com/".length());
        String[] parts = path.split("/");
        if (parts.length < 2 || parts[0].isBlank() || parts[1].isBlank()) {
            throw new IllegalArgumentException("Invalid GitHub repository URL");
        }
        return new String[]{parts[0], parts[1]};
    }

    private boolean isImportantRootFile(String path) {
        String normalized = path.toLowerCase();
        return normalized.equals("package.json")
                || normalized.equals("pom.xml")
                || normalized.equals("build.gradle")
                || normalized.equals("settings.gradle")
                || normalized.equals("dockerfile")
                || normalized.equals("docker-compose.yml")
                || normalized.equals("vite.config.js")
                || normalized.equals("vite.config.ts")
                || normalized.equals("requirements.txt")
                || normalized.equals("pyproject.toml");
    }

    private String decodeContent(String value) {
        if (value == null || value.isBlank()) {
            return "";
        }
        byte[] bytes = Base64.getMimeDecoder().decode(value);
        return new String(bytes, StandardCharsets.UTF_8);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> mapValue(Object value) {
        return value instanceof Map<?, ?> map ? (Map<String, Object>) map : Map.of();
    }

    private String text(Map<String, Object> map, String key) {
        Object value = map == null ? null : map.get(key);
        return value == null ? "" : String.valueOf(value);
    }

    private String value(Map<String, Object> map, String key, String fallback) {
        String value = text(map, key);
        return value.isBlank() ? fallback : value;
    }

    private String firstLine(String value) {
        if (value == null) {
            return "";
        }
        int index = value.indexOf('\n');
        return index < 0 ? value : value.substring(0, index);
    }

    private String trim(String value, int limit) {
        if (value == null) {
            return "";
        }
        String clean = value.replace("\r", "").trim();
        return clean.length() <= limit ? clean : clean.substring(0, limit) + "...";
    }
}
