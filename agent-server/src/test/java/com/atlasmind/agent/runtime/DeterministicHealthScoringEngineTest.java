package com.atlasmind.agent.runtime;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.mockito.Mockito.mock;

class DeterministicHealthScoringEngineTest {

    private final DeterministicHealthScoringEngine engine =
            new DeterministicHealthScoringEngine(mock(JdbcTemplate.class));

    @Test
    void identicalEvidenceProducesIdenticalScoreAndHash() {
        Map<String, Object> project = Map.of(
                "id", 9L, "repositoryUrl", "https://github.com/acme/repo",
                "currentMilestone", "MVP", "releaseTarget", "2026-Q3",
                "techStack", "Java", "teamSize", 3);
        List<Map<String, Object>> evidence = List.of(
                citation("1", "README", "README with JUnit tests and .github/workflows/ci.yml"),
                citation("2", "COMMIT", "Add package configuration"));

        Map<String, Object> first = engine.score(project, evidence);
        Map<String, Object> second = engine.score(project, evidence);

        assertEquals(first.get("healthScore"), second.get("healthScore"));
        assertEquals(first.get("evidenceHash"), second.get("evidenceHash"));
    }

    @Test
    void changedEvidenceChangesTheSnapshotHash() {
        Map<String, Object> project = Map.of("id", 9L, "repositoryUrl", "repo");

        String first = engine.evidenceHash(project, List.of(citation("1", "README", "old")));
        String second = engine.evidenceHash(project, List.of(citation("1", "README", "new")));

        assertNotEquals(first, second);
    }

    private Map<String, Object> citation(String sourceId, String objectType, String snippet) {
        return Map.of(
                "sourceType", "GITHUB",
                "sourceId", sourceId,
                "objectType", objectType,
                "sourceRef", objectType,
                "title", objectType,
                "snippet", snippet
        );
    }
}
