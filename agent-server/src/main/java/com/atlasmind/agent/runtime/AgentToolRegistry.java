package com.atlasmind.agent.runtime;

import com.atlasmind.gateway.AiGateway;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

@Component
@RequiredArgsConstructor
public class AgentToolRegistry {

    private static final Set<String> TOOL_NAMES = Set.of(
            "getProjectProfile",
            "searchProjectEvidence",
            "searchProjectKnowledge",
            "getProjectMemory",
            "getRecentRuns",
            "getLatestReport",
            "calculateHealthScore"
    );

    private final JdbcTemplate jdbcTemplate;
    private final AiGateway aiGateway;
    private final DeterministicHealthScoringEngine scoringEngine;

    public boolean supports(String toolName) {
        return TOOL_NAMES.contains(toolName);
    }

    public List<Map<String, Object>> definitions() {
        return List.of(
                tool("getProjectProfile", "读取当前项目的目标、仓库、里程碑和技术栈", Map.of()),
                tool("searchProjectEvidence", "按关键词和类型检索当前项目真实 GitHub 证据",
                        Map.of("query", stringProperty("检索词，可为空"),
                                "objectTypes", arrayProperty("README/FILE_TREE/FILE/ISSUE/PR/COMMIT"),
                                "limit", integerProperty("返回条数，1 到 20"))),
                tool("searchProjectKnowledge", "检索管理端绑定到当前项目的公司规范和技术文档",
                        Map.of("query", stringProperty("与任务相关的检索问题"),
                                "limit", integerProperty("返回条数，1 到 10"))),
                tool("getProjectMemory", "读取当前项目已确认事实和历史 Agent 情节记忆",
                        Map.of("limit", integerProperty("返回条数，1 到 20"))),
                tool("getRecentRuns", "读取当前项目近期 Agent 运行及状态，避免重复工作",
                        Map.of("limit", integerProperty("返回条数，1 到 10"))),
                tool("getLatestReport", "读取当前项目最近一份指定类型产物",
                        Map.of("reportType", stringProperty("HEALTH_REPORT、ONBOARDING_GUIDE 或 DECISION_MEMO"))),
                tool("calculateHealthScore", "用固定规则和当前证据快照计算项目健康分；LLM 不得自行评分", Map.of())
        );
    }

    public Map<String, Object> execute(AgentTaskContext context, String toolName,
                                       Map<String, Object> arguments,
                                       List<Map<String, Object>> observations) {
        if (!supports(toolName)) {
            throw new IllegalArgumentException("Tool is not allowlisted: " + toolName);
        }
        return switch (toolName) {
            case "getProjectProfile" -> Map.of("project", context.project());
            case "searchProjectEvidence" -> Map.of("items", searchEvidence(context.projectId(), arguments));
            case "searchProjectKnowledge" -> Map.of("items", searchKnowledge(context, arguments));
            case "getProjectMemory" -> Map.of("items", projectMemory(context.projectId(), limit(arguments, 10, 20)));
            case "getRecentRuns" -> Map.of("items", recentRuns(context.projectId(), context.runId(), limit(arguments, 5, 10)));
            case "getLatestReport" -> Map.of("report", latestReport(context.projectId(), arguments));
            case "calculateHealthScore" -> {
                List<Map<String, Object>> canonicalEvidence = canonicalEvidence(context.projectId());
                yield Map.of(
                        "scoring", scoringEngine.score(context.project(), canonicalEvidence),
                        "canonicalEvidenceCount", canonicalEvidence.size()
                );
            }
            default -> throw new IllegalArgumentException("Tool is not allowlisted: " + toolName);
        };
    }

    public List<Map<String, Object>> citationsFrom(List<Map<String, Object>> observations) {
        Map<String, Map<String, Object>> unique = new LinkedHashMap<>();
        for (Map<String, Object> observation : observations) {
            String toolName = text(observation, "toolName");
            if (!Set.of("searchProjectEvidence", "searchProjectKnowledge").contains(toolName)) continue;
            Object outputValue = observation.get("output");
            if (!(outputValue instanceof Map<?, ?> output)) continue;
            Object itemsValue = output.get("items");
            if (!(itemsValue instanceof List<?> items)) continue;
            for (Object itemValue : items) {
                if (!(itemValue instanceof Map<?, ?> item)) continue;
                Map<String, Object> citation = new HashMap<>();
                item.forEach((key, value) -> citation.put(String.valueOf(key), value));
                if (!citation.containsKey("sourceId")) continue;
                String key = text(citation, "sourceType") + ":" + text(citation, "sourceId");
                unique.putIfAbsent(key, citation);
            }
        }
        return new ArrayList<>(unique.values());
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> scoringFrom(List<Map<String, Object>> observations) {
        for (int index = observations.size() - 1; index >= 0; index--) {
            Object output = observations.get(index).get("output");
            if (output instanceof Map<?, ?> map && map.get("scoring") instanceof Map<?, ?> scoring) {
                Map<String, Object> result = new HashMap<>();
                scoring.forEach((key, value) -> result.put(String.valueOf(key), value));
                return result;
            }
        }
        return Map.of();
    }

    private List<Map<String, Object>> searchEvidence(Long projectId, Map<String, Object> arguments) {
        int limit = limit(arguments, 8, 20);
        String query = text(arguments, "query").toLowerCase(Locale.ROOT);
        Set<String> requestedTypes = stringSet(arguments.get("objectTypes"));
        List<Map<String, Object>> rows = jdbcTemplate.queryForList("""
                SELECT id AS sourceId, source_type AS sourceType, object_type AS objectType,
                       title, source_ref AS sourceRef, source_url AS sourceUrl,
                       content_snippet AS snippet, confidence_score AS score,
                       observed_at AS observedAt
                FROM project_evidence
                WHERE project_id=?
                ORDER BY confidence_score DESC, update_time DESC
                LIMIT 100
                """, projectId);
        List<Map<String, Object>> filtered = rows.stream()
                .filter(row -> requestedTypes.isEmpty()
                        || requestedTypes.contains(text(row, "objectType").toUpperCase(Locale.ROOT)))
                .filter(row -> query.isBlank() || (text(row, "title") + " " + text(row, "sourceRef")
                        + " " + text(row, "snippet")).toLowerCase(Locale.ROOT).contains(query))
                .limit(limit)
                .toList();
        if (!filtered.isEmpty() || query.isBlank()) return filtered;
        return rows.stream()
                .filter(row -> requestedTypes.isEmpty()
                        || requestedTypes.contains(text(row, "objectType").toUpperCase(Locale.ROOT)))
                .limit(limit)
                .toList();
    }

    private List<Map<String, Object>> canonicalEvidence(Long projectId) {
        return jdbcTemplate.queryForList("""
                SELECT id AS sourceId, source_type AS sourceType, object_type AS objectType,
                       title, source_ref AS sourceRef, source_url AS sourceUrl,
                       content_snippet AS snippet, confidence_score AS score,
                       observed_at AS observedAt
                FROM project_evidence
                WHERE project_id=?
                ORDER BY object_type, source_ref, evidence_hash
                LIMIT 500
                """, projectId);
    }

    private List<Map<String, Object>> searchKnowledge(AgentTaskContext context, Map<String, Object> arguments) {
        int limit = limit(arguments, 5, 10);
        String query = text(arguments, "query");
        if (query.isBlank()) query = context.question();
        List<Map<String, Object>> documents = jdbcTemplate.queryForList("""
                SELECT d.id, d.title, s.name AS spaceName
                FROM project_kb_document pkd
                JOIN kb_document d ON d.id=pkd.document_id
                JOIN kb_space s ON s.id=d.space_id
                WHERE pkd.project_id=? AND d.deleted=0 AND d.status='READY'
                  AND s.deleted=0 AND s.enabled=1
                ORDER BY pkd.create_time DESC, d.update_time DESC
                LIMIT 8
                """, context.projectId());
        List<Map<String, Object>> results = new ArrayList<>();
        for (Map<String, Object> document : documents) {
            if (results.size() >= limit) break;
            Map<String, Object> response = aiGateway.testRetrieval(Map.of(
                    "message", query,
                    "documentId", document.get("id"),
                    "topK", Math.min(3, limit - results.size())
            ));
            Object hitsValue = response.get("hits");
            if (!(hitsValue instanceof List<?> hits)) continue;
            for (Object hitValue : hits) {
                if (results.size() >= limit) break;
                if (!(hitValue instanceof Map<?, ?> hit)) continue;
                Map<String, Object> item = new HashMap<>();
                hit.forEach((key, value) -> item.put(String.valueOf(key), value));
                item.put("sourceType", "DOCUMENT");
                item.put("objectType", "KB_DOCUMENT");
                item.put("sourceId", String.valueOf(document.get("id")));
                item.put("sourceRef", document.get("spaceName") + " / " + document.get("title"));
                item.putIfAbsent("title", document.get("title"));
                if (!item.containsKey("snippet") && item.containsKey("content")) {
                    item.put("snippet", item.get("content"));
                }
                results.add(item);
            }
        }
        return results;
    }

    private List<Map<String, Object>> projectMemory(Long projectId, int limit) {
        return jdbcTemplate.queryForList("""
                SELECT id, memory_type AS memoryType, title, content, source_type AS sourceType,
                       source_id AS sourceId, confirmed, create_time AS createTime
                FROM agent_project_memory
                WHERE project_id=?
                ORDER BY confirmed DESC, update_time DESC LIMIT ?
                """, projectId, limit);
    }

    private List<Map<String, Object>> recentRuns(Long projectId, Long currentRunId, int limit) {
        return jdbcTemplate.queryForList("""
                SELECT id, run_type AS runType, question, status, current_step AS currentStep,
                       error_message AS errorMessage, create_time AS createTime
                FROM agent_run
                WHERE project_id=? AND id<>?
                ORDER BY id DESC LIMIT ?
                """, projectId, currentRunId, limit);
    }

    private Map<String, Object> latestReport(Long projectId, Map<String, Object> arguments) {
        String reportType = text(arguments, "reportType").toUpperCase(Locale.ROOT);
        if (!Set.of("HEALTH_REPORT", "ONBOARDING_GUIDE", "DECISION_MEMO").contains(reportType)) {
            reportType = "HEALTH_REPORT";
        }
        List<Map<String, Object>> rows = jdbcTemplate.queryForList("""
                SELECT id, report_type AS reportType, title, summary, health_status AS healthStatus,
                       health_score AS healthScore, evidence_hash AS evidenceHash,
                       analysis_mode AS analysisMode, create_time AS createTime
                FROM agent_report
                WHERE project_id=? AND report_type=?
                ORDER BY id DESC LIMIT 1
                """, projectId, reportType);
        return rows.isEmpty() ? Map.of() : rows.get(0);
    }

    private Map<String, Object> tool(String name, String description,
                                     Map<String, Object> properties) {
        return Map.of(
                "type", "function",
                "function", Map.of(
                        "name", name,
                        "description", description,
                        "parameters", Map.of(
                                "type", "object",
                                "properties", properties,
                                "additionalProperties", false
                        )
                )
        );
    }

    private Map<String, Object> stringProperty(String description) {
        return Map.of("type", "string", "description", description);
    }

    private Map<String, Object> integerProperty(String description) {
        return Map.of("type", "integer", "description", description, "minimum", 1);
    }

    private Map<String, Object> arrayProperty(String description) {
        return Map.of("type", "array", "description", description,
                "items", Map.of("type", "string"));
    }

    private int limit(Map<String, Object> arguments, int fallback, int maximum) {
        Object value = arguments == null ? null : arguments.get("limit");
        int parsed = value instanceof Number number ? number.intValue() : fallback;
        return Math.max(1, Math.min(maximum, parsed));
    }

    private Set<String> stringSet(Object value) {
        if (!(value instanceof List<?> list)) return Set.of();
        return list.stream().map(String::valueOf).map(item -> item.toUpperCase(Locale.ROOT))
                .collect(java.util.stream.Collectors.toSet());
    }

    private String text(Map<String, Object> source, String key) {
        Object value = source == null ? null : source.get(key);
        return value == null ? "" : String.valueOf(value);
    }
}
