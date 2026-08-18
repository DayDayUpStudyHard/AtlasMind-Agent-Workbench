package com.atlasmind.config;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AgentWorkbenchSchemaInitializerTest {

    @Mock
    private JdbcTemplate jdbcTemplate;

    @Test
    void migratesColumnsRequiredToStartAndMonitorAgentRuns() {
        when(jdbcTemplate.queryForObject(anyString(), eq(Integer.class), any(), any()))
                .thenReturn(0);

        new AgentWorkbenchSchemaInitializer(jdbcTemplate)
                .addAgentRunRuntimeColumnsIfMissing();

        verify(jdbcTemplate).execute(contains("ADD COLUMN `input_json` LONGTEXT"));
        verify(jdbcTemplate).execute(contains("ADD COLUMN `limited_diagnostics` JSON"));
        verify(jdbcTemplate).execute(contains("ADD COLUMN `last_heartbeat_at` DATETIME"));
    }
}
