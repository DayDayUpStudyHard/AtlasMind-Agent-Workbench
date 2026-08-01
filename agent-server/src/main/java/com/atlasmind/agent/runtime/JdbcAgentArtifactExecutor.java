package com.atlasmind.agent.runtime;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.Map;

@Component
@RequiredArgsConstructor
public class JdbcAgentArtifactExecutor implements AgentArtifactExecutor {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    @Override
    @Transactional
    public ArtifactExecutionResult persistDraft(Long projectId, Long runId, String taskType,
                                                Map<String, Object> artifact) {
        boolean health = "HEALTH_ANALYSIS".equals(taskType);
        Long reportId = insert("""
                INSERT INTO agent_report
                (project_id, run_id, report_type, title, summary, health_status, health_score,
                 dimensions_json, risks_json, plan_json, citations_json,
                 scoring_version, evidence_hash, analysis_mode, scoring_rationale_json,
                 content_json, report_markdown, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'DRAFT')
                """,
                projectId, runId, artifact.get("reportType"), artifact.get("title"), artifact.get("summary"),
                health ? artifact.get("healthStatus") : null,
                health ? artifact.get("healthScore") : 0,
                health ? json(artifact.get("dimensions")) : null,
                json(artifact.get("risks")), json(artifact.get("plan")), json(artifact.get("citations")),
                health ? artifact.get("scoringVersion") : null,
                artifact.get("evidenceHash"), artifact.get("analysisMode"),
                health ? json(artifact.get("scoringRationale")) : null,
                json(artifact.getOrDefault("content", artifact)), artifact.get("reportMarkdown"));

        Long actionId = insert("""
                INSERT INTO agent_action
                (project_id, run_id, action_type, status, title, payload_json)
                VALUES (?,?,'CREATE_GITHUB_ISSUE','PENDING_APPROVAL',?,?)
                """, projectId, runId, artifact.get("issueTitle"),
                json(Map.of("body", artifact.getOrDefault("issueBody", artifact.get("reportMarkdown")),
                        "source", artifact.get("reportType"))));

        if (health) {
            jdbcTemplate.update("""
                    UPDATE agent_project
                    SET health_status=?, health_score=?, last_run_id=?, last_run_at=NOW()
                    WHERE id=?
                    """, artifact.get("healthStatus"), artifact.get("healthScore"), runId, projectId);
        }
        return new ArtifactExecutionResult(reportId, actionId);
    }

    private Long insert(String sql, Object... args) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement statement = connection.prepareStatement(sql, Statement.RETURN_GENERATED_KEYS);
            for (int index = 0; index < args.length; index++) {
                statement.setObject(index + 1, args[index]);
            }
            return statement;
        }, keyHolder);
        if (keyHolder.getKey() == null) {
            throw new IllegalStateException("Database did not return a generated artifact id");
        }
        return keyHolder.getKey().longValue();
    }

    private String json(Object value) {
        try {
            return objectMapper.writeValueAsString(value == null ? Map.of() : value);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("Unable to serialize Agent artifact", e);
        }
    }
}
