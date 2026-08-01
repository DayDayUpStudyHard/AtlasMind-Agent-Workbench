package com.atlasmind.agent.runtime;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;

@Component
public class DeterministicHealthScoringEngine {

    public static final String SCORING_VERSION = "v2-harness";
    public static final String ANALYSIS_MODE = "deterministic-score + agent-harness-explanation";

    private final JdbcTemplate jdbcTemplate;

    public DeterministicHealthScoringEngine(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Map<String, Object> score(Map<String, Object> project, List<Map<String, Object>> citations) {
        Map<String, Integer> counts = countByType(citations);
        String evidenceText = normalizedEvidenceText(project, citations);
        boolean hasGithub = citations.stream().anyMatch(item -> "GITHUB".equals(text(item, "sourceType")));
        boolean hasReadme = counts.getOrDefault("README", 0) > 0;
        boolean hasFileTree = counts.getOrDefault("FILE_TREE", 0) > 0;
        boolean hasFile = counts.getOrDefault("FILE", 0) > 0;
        boolean hasCommit = counts.getOrDefault("COMMIT", 0) > 0;
        boolean hasIssue = counts.getOrDefault("ISSUE", 0) > 0;
        boolean hasPr = counts.getOrDefault("PR", 0) > 0;
        boolean hasDependencies = containsAny(evidenceText, "pom.xml", "package.json", "pyproject.toml",
                "build.gradle", "requirements.txt", "pnpm-lock", "yarn.lock", "package-lock");
        boolean hasTests = containsAny(evidenceText, "test", "tests", "pytest", "junit", "vitest", "jest",
                "coverage", "单元测试", "测试");
        boolean hasCi = containsAny(evidenceText, ".github/workflows", "github actions", "ci.yml", "ci.yaml",
                "jenkins", "gitlab-ci", "pipeline", "流水线", "持续集成");
        boolean hasMilestone = !text(project, "currentMilestone").isBlank();
        boolean hasReleaseTarget = !text(project, "releaseTarget").isBlank();
        boolean hasTechStack = !text(project, "techStack").isBlank();
        boolean hasTeam = integer(project.get("teamSize")) > 0;

        List<Map<String, Object>> rationale = new ArrayList<>();
        int delivery = 45
                + signal(rationale, "交付进展", hasIssue || hasPr, 25, "Issue/PR 数据")
                + signal(rationale, "交付进展", hasMilestone, 15, "当前里程碑")
                + signal(rationale, "交付进展", hasReleaseTarget, 10, "目标版本")
                + signal(rationale, "交付进展", hasCommit, 5, "近期提交");
        int quality = 35
                + signal(rationale, "工程质量", hasTests, 25, "测试证据")
                + signal(rationale, "工程质量", hasCi, 25, "CI/CD 证据")
                + signal(rationale, "工程质量", hasDependencies, 10, "依赖配置")
                + signal(rationale, "工程质量", hasPr, 5, "PR 评审");
        int architecture = 45
                + signal(rationale, "架构可维护性", hasReadme, 15, "README")
                + signal(rationale, "架构可维护性", hasFileTree, 15, "目录结构")
                + signal(rationale, "架构可维护性", hasDependencies, 15, "构建配置")
                + signal(rationale, "架构可维护性", hasTechStack, 10, "技术栈");
        int risk = 45
                + signal(rationale, "风险暴露", hasGithub, 15, "真实仓库证据")
                + signal(rationale, "风险暴露", hasCi, 10, "构建信号")
                + signal(rationale, "风险暴露", hasTests, 10, "质量信号")
                + signal(rationale, "风险暴露", hasIssue || hasPr, 10, "协作风险信号")
                + signal(rationale, "风险暴露", hasReadme || hasFile, 10, "代码/文档证据");
        int collaboration = 40
                + signal(rationale, "协作活跃度", hasCommit, 25, "提交活跃")
                + signal(rationale, "协作活跃度", hasPr, 20, "PR 协作")
                + signal(rationale, "协作活跃度", hasIssue, 10, "Issue 协作")
                + signal(rationale, "协作活跃度", hasTeam, 5, "团队规模");

        List<Map<String, Object>> dimensions = List.of(
                dimension("交付进展", delivery, 25),
                dimension("工程质量", quality, 25),
                dimension("架构可维护性", architecture, 20),
                dimension("风险暴露", risk, 15),
                dimension("协作活跃度", collaboration, 15)
        );
        int healthScore = clamp((int) Math.round(delivery * .25 + quality * .25
                + architecture * .20 + risk * .15 + collaboration * .15));
        String evidenceHash = evidenceHash(project, citations);
        List<Map<String, Object>> previous = jdbcTemplate.queryForList("""
                SELECT id, health_score AS healthScore
                FROM agent_report
                WHERE project_id=? AND report_type='HEALTH_REPORT' AND evidence_hash=?
                ORDER BY id DESC LIMIT 1
                """, project.get("id"), evidenceHash);

        Map<String, Object> result = new HashMap<>();
        result.put("healthScore", healthScore);
        result.put("healthStatus", healthScore >= 80 ? "HEALTHY" : healthScore >= 65 ? "WATCH" : "AT_RISK");
        result.put("dimensions", dimensions);
        result.put("rationale", rationale);
        result.put("scoringVersion", SCORING_VERSION);
        result.put("evidenceHash", evidenceHash);
        result.put("analysisMode", ANALYSIS_MODE);
        result.put("snapshotReused", !previous.isEmpty());
        if (!previous.isEmpty()) {
            result.put("previousReportId", previous.get(0).get("id"));
            result.put("previousHealthScore", previous.get(0).get("healthScore"));
        }
        return result;
    }

    public String evidenceHash(Map<String, Object> project, List<Map<String, Object>> citations) {
        StringBuilder value = new StringBuilder()
                .append("project:").append(text(project, "id")).append('\n')
                .append("repo:").append(text(project, "repositoryUrl")).append('\n')
                .append("milestone:").append(text(project, "currentMilestone")).append('\n')
                .append("release:").append(text(project, "releaseTarget")).append('\n');
        citations.stream()
                .map(item -> text(item, "sourceType") + "|" + text(item, "objectType") + "|"
                        + text(item, "sourceId") + "|" + text(item, "sourceRef") + "|"
                        + text(item, "title") + "|" + text(item, "snippet"))
                .sorted()
                .forEach(line -> value.append(line).append('\n'));
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.toString().getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException("Unable to hash evidence snapshot", e);
        }
    }

    private int signal(List<Map<String, Object>> rationale, String dimension,
                       boolean present, int points, String title) {
        rationale.add(Map.of(
                "dimension", dimension,
                "title", title,
                "type", present ? "POSITIVE" : "MISSING",
                "impact", present ? points : -points,
                "note", present ? "已找到可验证证据" : "当前证据快照中未找到，按缺失项处理"
        ));
        return present ? points : 0;
    }

    private Map<String, Object> dimension(String name, int score, int weight) {
        int normalized = clamp(score);
        return Map.of("name", name, "score", normalized, "weight", weight,
                "note", "由 v2-harness 固定信号规则计算，当前为 " + normalized + "/100");
    }

    private Map<String, Integer> countByType(List<Map<String, Object>> citations) {
        Map<String, Integer> counts = new HashMap<>();
        for (Map<String, Object> citation : citations) {
            counts.merge(text(citation, "objectType").toUpperCase(), 1, Integer::sum);
        }
        return counts;
    }

    private String normalizedEvidenceText(Map<String, Object> project, List<Map<String, Object>> citations) {
        StringBuilder value = new StringBuilder();
        for (String key : List.of("description", "businessScope", "currentMilestone", "releaseTarget", "techStack")) {
            value.append(text(project, key)).append('\n');
        }
        for (Map<String, Object> item : citations) {
            value.append(text(item, "objectType")).append('\n')
                    .append(text(item, "title")).append('\n')
                    .append(text(item, "sourceRef")).append('\n')
                    .append(text(item, "snippet")).append('\n');
        }
        return value.toString().toLowerCase();
    }

    private boolean containsAny(String value, String... keywords) {
        for (String keyword : keywords) {
            if (value.contains(keyword.toLowerCase())) return true;
        }
        return false;
    }

    private String text(Map<String, Object> source, String key) {
        Object value = source == null ? null : source.get(key);
        return value == null ? "" : String.valueOf(value);
    }

    private int integer(Object value) {
        if (value instanceof Number number) return number.intValue();
        try {
            return value == null ? 0 : Integer.parseInt(String.valueOf(value));
        } catch (NumberFormatException ignored) {
            return 0;
        }
    }

    private int clamp(int value) {
        return Math.max(0, Math.min(100, value));
    }
}
