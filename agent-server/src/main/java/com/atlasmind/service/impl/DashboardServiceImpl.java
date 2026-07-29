package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.KbDocument;
import com.atlasmind.entity.KbIngestJob;
import com.atlasmind.mapper.KbDocumentMapper;
import com.atlasmind.mapper.KbIngestJobMapper;
import com.atlasmind.service.DashboardService;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Aggregates the management-console overview around Agent operations.
 */
@Service
@RequiredArgsConstructor
public class DashboardServiceImpl implements DashboardService {

    private final KbDocumentMapper documentMapper;
    private final KbIngestJobMapper jobMapper;
    private final JdbcTemplate jdbcTemplate;

    @Override
    public Map<String, Object> overview() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("projectCount", count("SELECT COUNT(*) FROM agent_project WHERE deleted=0"));
        result.put("knowledgeDocumentCount", documentMapper.selectCount(
                new LambdaQueryWrapper<KbDocument>().eq(KbDocument::getDeleted, 0)
        ));
        result.put("evidenceCount", count("SELECT COUNT(*) FROM project_evidence"));
        result.put("activeRuns", count("""
                SELECT COUNT(*) FROM agent_run
                WHERE status IN ('CREATED','CONTEXT_BUILDING','ANALYZING','VERIFYING','PLANNING')
                """));
        result.put("pendingApprovals", count("SELECT COUNT(*) FROM agent_action WHERE status='PENDING_APPROVAL'"));
        result.put("failedIngestJobCount", jobMapper.selectCount(
                new LambdaQueryWrapper<KbIngestJob>().eq(KbIngestJob::getStatus, "FAILED")
        ));
        result.put("failedSyncJobCount", count("SELECT COUNT(*) FROM project_sync_job WHERE status='FAILED'"));
        result.put("recentRuns", jdbcTemplate.queryForList("""
                SELECT r.id, r.project_id AS projectId, p.name AS projectName, r.status, r.progress,
                       r.current_step AS currentStep, r.question, r.create_time AS createTime
                FROM agent_run r
                JOIN agent_project p ON p.id = r.project_id
                WHERE p.deleted=0
                ORDER BY r.id DESC
                LIMIT 6
                """));
        result.put("recentSyncJobs", jdbcTemplate.queryForList("""
                SELECT j.id, j.project_id AS projectId, p.name AS projectName, j.status, j.progress,
                       j.message, j.error_message AS errorMessage, j.create_time AS createTime
                FROM project_sync_job j
                JOIN agent_project p ON p.id = j.project_id
                WHERE p.deleted=0
                ORDER BY j.id DESC
                LIMIT 6
                """));
        result.put("recentReports", jdbcTemplate.queryForList("""
                SELECT rp.id, rp.project_id AS projectId, p.name AS projectName, rp.title,
                       rp.health_status AS healthStatus, rp.health_score AS healthScore,
                       rp.status, rp.create_time AS createTime
                FROM agent_report rp
                JOIN agent_project p ON p.id = rp.project_id
                WHERE p.deleted=0
                ORDER BY rp.id DESC
                LIMIT 6
                """));
        return result;
    }

    private int count(String sql) {
        Number value = jdbcTemplate.queryForObject(sql, Integer.class);
        return value == null ? 0 : value.intValue();
    }
}
