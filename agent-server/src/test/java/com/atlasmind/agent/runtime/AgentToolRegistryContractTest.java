package com.atlasmind.agent.runtime;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import com.atlasmind.gateway.AiGateway;

import static org.mockito.Mockito.mock;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AgentToolRegistryContractTest {

    @Test
    void documentsTheOnlySupportedToolNames() {
        AgentToolRegistry registry = new AgentToolRegistry(
                mock(JdbcTemplate.class), mock(AiGateway.class),
                mock(DeterministicHealthScoringEngine.class));

        assertTrue(registry.supports("searchProjectEvidence"));
        assertTrue(registry.supports("calculateHealthScore"));
        assertFalse(registry.supports("executeSql"));
        assertFalse(registry.supports("createGithubIssue"));
    }
}
