package com.atlasmind.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;
import java.util.Map;

@Mapper
public interface AiObservabilityMapper {

    @Update("""
            CREATE TABLE IF NOT EXISTS kb_tool_call (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                trace_id BIGINT NOT NULL,
                name VARCHAR(100) NOT NULL,
                status VARCHAR(30) NOT NULL,
                latency_ms BIGINT DEFAULT 0,
                input_summary VARCHAR(1000),
                output_summary VARCHAR(1000),
                error_message TEXT,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_trace (trace_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
    void ensureToolCallTable();

    @Select("""
            <script>
            SELECT
                t.id AS traceId,
                t.message_id AS userMessageId,
                m.session_id AS sessionId,
                m.content AS question,
                t.retrieval_type AS retrievalType,
                t.top_k AS topK,
                t.latency_ms AS retrievalLatencyMs,
                t.fallback_reason AS fallbackReason,
                t.hit_count AS hitCount,
                t.create_time AS createTime,
                a.id AS assistantMessageId,
                a.content AS answer,
                a.model AS model,
                a.latency_ms AS llmLatencyMs
            FROM kb_retrieval_trace t
            JOIN kb_qa_message m ON m.id = t.message_id
            LEFT JOIN kb_qa_message a ON a.id = (
                SELECT am.id
                FROM kb_qa_message am
                WHERE am.session_id = m.session_id
                  AND am.role = 'assistant'
                  AND am.id &gt; m.id
                ORDER BY am.id ASC
                LIMIT 1
            )
            WHERE 1 = 1
            <if test="keyword != null and keyword != ''">
                AND (m.content LIKE CONCAT('%', #{keyword}, '%')
                     OR a.content LIKE CONCAT('%', #{keyword}, '%'))
            </if>
            ORDER BY t.create_time DESC, t.id DESC
            LIMIT #{offset}, #{size}
            </script>
            """)
    List<Map<String, Object>> listTraces(@Param("offset") long offset,
                                         @Param("size") long size,
                                         @Param("keyword") String keyword);

    @Select("""
            <script>
            SELECT COUNT(*)
            FROM kb_retrieval_trace t
            JOIN kb_qa_message m ON m.id = t.message_id
            LEFT JOIN kb_qa_message a ON a.id = (
                SELECT am.id
                FROM kb_qa_message am
                WHERE am.session_id = m.session_id
                  AND am.role = 'assistant'
                  AND am.id &gt; m.id
                ORDER BY am.id ASC
                LIMIT 1
            )
            WHERE 1 = 1
            <if test="keyword != null and keyword != ''">
                AND (m.content LIKE CONCAT('%', #{keyword}, '%')
                     OR a.content LIKE CONCAT('%', #{keyword}, '%'))
            </if>
            </script>
            """)
    long countTraces(@Param("keyword") String keyword);

    @Select("""
            SELECT
                t.id AS traceId,
                t.message_id AS userMessageId,
                m.session_id AS sessionId,
                m.content AS question,
                t.retrieval_type AS retrievalType,
                t.top_k AS topK,
                t.latency_ms AS retrievalLatencyMs,
                t.fallback_reason AS fallbackReason,
                t.hit_count AS hitCount,
                t.create_time AS createTime,
                a.id AS assistantMessageId,
                a.content AS answer,
                a.model AS model,
                a.latency_ms AS llmLatencyMs
            FROM kb_retrieval_trace t
            JOIN kb_qa_message m ON m.id = t.message_id
            LEFT JOIN kb_qa_message a ON a.id = (
                SELECT am.id
                FROM kb_qa_message am
                WHERE am.session_id = m.session_id
                  AND am.role = 'assistant'
                  AND am.id > m.id
                ORDER BY am.id ASC
                LIMIT 1
            )
            WHERE t.id = #{traceId}
            LIMIT 1
            """)
    Map<String, Object> getTrace(@Param("traceId") Long traceId);

    @Select("""
            SELECT
                id,
                trace_id AS traceId,
                source_type AS sourceType,
                source_id AS sourceId,
                chunk_id AS chunkId,
                title,
                score,
                snippet,
                rank_no AS rankNo,
                create_time AS createTime
            FROM kb_retrieval_hit
            WHERE trace_id = #{traceId}
            ORDER BY rank_no ASC, id ASC
            """)
    List<Map<String, Object>> listHits(@Param("traceId") Long traceId);

    @Select("""
            SELECT
                id,
                trace_id AS traceId,
                name,
                status,
                latency_ms AS latencyMs,
                input_summary AS inputSummary,
                output_summary AS outputSummary,
                error_message AS errorMessage,
                create_time AS createTime
            FROM kb_tool_call
            WHERE trace_id = #{traceId}
            ORDER BY id ASC
            """)
    List<Map<String, Object>> listToolCalls(@Param("traceId") Long traceId);

    @Select("""
            <script>
            SELECT
                r.id AS runId,
                r.subject_type AS subjectType,
                r.subject_id AS subjectId,
                CASE
                    WHEN r.subject_type = 'CONTRACT_CASE' THEN c.case_key
                    ELSE p.project_key
                END AS subjectKey,
                CASE
                    WHEN r.subject_type = 'CONTRACT_CASE' THEN c.title
                    ELSE p.name
                END AS subjectTitle,
                r.project_id AS projectId,
                r.run_type AS runType,
                r.trigger_type AS triggerType,
                r.question,
                r.status,
                r.progress,
                r.current_step AS currentStep,
                r.error_message AS errorMessage,
                r.started_at AS startedAt,
                r.finished_at AS finishedAt,
                r.last_heartbeat_at AS lastHeartbeatAt,
                r.create_time AS createTime,
                (SELECT COUNT(*) FROM agent_run_trace t WHERE t.run_id = r.id) AS traceCount,
                (SELECT COUNT(*) FROM agent_tool_call tc WHERE tc.run_id = r.id) AS toolCallCount,
                (SELECT COUNT(*) FROM agent_tool_call tc WHERE tc.run_id = r.id AND tc.status = 'FAILED') AS failedToolCallCount,
                (SELECT COUNT(*) FROM agent_report rp WHERE rp.run_id = r.id) AS reportCount,
                (SELECT COUNT(*) FROM agent_action a WHERE a.run_id = r.id) AS actionCount
            FROM agent_run r
            LEFT JOIN contract_case c ON c.id = r.subject_id AND r.subject_type = 'CONTRACT_CASE'
            LEFT JOIN agent_project p ON p.id = r.project_id
            WHERE 1 = 1
            <if test="subjectType != null and subjectType != ''">
                AND r.subject_type = #{subjectType}
            </if>
            <if test="runType != null and runType != ''">
                AND r.run_type = #{runType}
            </if>
            <if test="status != null and status != ''">
                AND r.status = #{status}
            </if>
            <if test="keyword != null and keyword != ''">
                AND (
                    r.question LIKE CONCAT('%', #{keyword}, '%')
                    OR r.run_type LIKE CONCAT('%', #{keyword}, '%')
                    OR r.current_step LIKE CONCAT('%', #{keyword}, '%')
                    OR c.title LIKE CONCAT('%', #{keyword}, '%')
                    OR c.case_key LIKE CONCAT('%', #{keyword}, '%')
                    OR p.name LIKE CONCAT('%', #{keyword}, '%')
                    OR p.project_key LIKE CONCAT('%', #{keyword}, '%')
                )
            </if>
            ORDER BY r.id DESC
            LIMIT #{offset}, #{size}
            </script>
            """)
    List<Map<String, Object>> listAgentRuns(@Param("offset") long offset,
                                            @Param("size") long size,
                                            @Param("keyword") String keyword,
                                            @Param("subjectType") String subjectType,
                                            @Param("runType") String runType,
                                            @Param("status") String status);

    @Select("""
            <script>
            SELECT COUNT(*)
            FROM agent_run r
            LEFT JOIN contract_case c ON c.id = r.subject_id AND r.subject_type = 'CONTRACT_CASE'
            LEFT JOIN agent_project p ON p.id = r.project_id
            WHERE 1 = 1
            <if test="subjectType != null and subjectType != ''">
                AND r.subject_type = #{subjectType}
            </if>
            <if test="runType != null and runType != ''">
                AND r.run_type = #{runType}
            </if>
            <if test="status != null and status != ''">
                AND r.status = #{status}
            </if>
            <if test="keyword != null and keyword != ''">
                AND (
                    r.question LIKE CONCAT('%', #{keyword}, '%')
                    OR r.run_type LIKE CONCAT('%', #{keyword}, '%')
                    OR r.current_step LIKE CONCAT('%', #{keyword}, '%')
                    OR c.title LIKE CONCAT('%', #{keyword}, '%')
                    OR c.case_key LIKE CONCAT('%', #{keyword}, '%')
                    OR p.name LIKE CONCAT('%', #{keyword}, '%')
                    OR p.project_key LIKE CONCAT('%', #{keyword}, '%')
                )
            </if>
            </script>
            """)
    long countAgentRuns(@Param("keyword") String keyword,
                        @Param("subjectType") String subjectType,
                        @Param("runType") String runType,
                        @Param("status") String status);

    @Select("""
            SELECT
                r.id AS runId,
                r.subject_type AS subjectType,
                r.subject_id AS subjectId,
                CASE
                    WHEN r.subject_type = 'CONTRACT_CASE' THEN c.case_key
                    ELSE p.project_key
                END AS subjectKey,
                CASE
                    WHEN r.subject_type = 'CONTRACT_CASE' THEN c.title
                    ELSE p.name
                END AS subjectTitle,
                r.project_id AS projectId,
                r.run_type AS runType,
                r.trigger_type AS triggerType,
                r.question,
                r.input_json AS inputJson,
                r.status,
                r.progress,
                r.current_step AS currentStep,
                r.error_message AS errorMessage,
                r.started_at AS startedAt,
                r.finished_at AS finishedAt,
                r.last_heartbeat_at AS lastHeartbeatAt,
                r.create_time AS createTime,
                r.update_time AS updateTime
            FROM agent_run r
            LEFT JOIN contract_case c ON c.id = r.subject_id AND r.subject_type = 'CONTRACT_CASE'
            LEFT JOIN agent_project p ON p.id = r.project_id
            WHERE r.id = #{runId}
            LIMIT 1
            """)
    Map<String, Object> getAgentRun(@Param("runId") Long runId);

    @Select("""
            SELECT id, run_id AS runId, event_type AS eventType,
                   sequence_no AS sequenceNo, summary, payload_json AS payloadJson,
                   create_time AS createTime
            FROM agent_run_trace
            WHERE run_id = #{runId}
            ORDER BY sequence_no ASC, id ASC
            """)
    List<Map<String, Object>> listAgentRunTraces(@Param("runId") Long runId);

    @Select("""
            SELECT id, run_id AS runId, plan_step_id AS planStepId,
                   call_id AS callId, tool_name AS toolName,
                   input_json AS inputJson, output_json AS outputJson,
                   status, latency_ms AS latencyMs, error_message AS errorMessage,
                   create_time AS createTime, update_time AS updateTime
            FROM agent_tool_call
            WHERE run_id = #{runId}
            ORDER BY id ASC
            """)
    List<Map<String, Object>> listAgentRunToolCalls(@Param("runId") Long runId);

    @Select("""
            SELECT id, report_type AS reportType, title, summary,
                   health_status AS healthStatus, health_score AS healthScore,
                   dimensions_json AS dimensionsJson, risks_json AS risksJson,
                   plan_json AS planJson, citations_json AS citationsJson,
                   scoring_version AS scoringVersion, evidence_hash AS evidenceHash,
                   analysis_mode AS analysisMode,
                   scoring_rationale_json AS scoringRationaleJson,
                   content_json AS contentJson,
                   report_markdown AS reportMarkdown,
                   status,
                   create_time AS createTime
            FROM agent_report
            WHERE run_id = #{runId}
            ORDER BY id DESC
            """)
    List<Map<String, Object>> listAgentRunReports(@Param("runId") Long runId);

    @Select("""
            SELECT id, case_id AS caseId, run_id AS runId,
                   rule_id AS ruleId, rule_key AS ruleKey,
                   clause_type AS clauseType, severity, status, title,
                   description, impact,
                   remediation_advice AS remediationAdvice,
                   negotiation_advice AS negotiationAdvice,
                   verification_points AS verificationPoints,
                   contract_citation AS contractCitation,
                   policy_citation AS policyCitation,
                   suggested_action AS suggestedAction,
                   create_time AS createTime, update_time AS updateTime
            FROM contract_review_finding
            WHERE run_id = #{runId}
            ORDER BY FIELD(severity, 'HIGH', 'MEDIUM', 'LOW'), id ASC
            """)
    List<Map<String, Object>> listAgentRunFindings(@Param("runId") Long runId);

    @Select("""
            SELECT id, action_type AS actionType, status, title,
                   payload_json AS payloadJson, external_id AS externalId,
                   approved_by AS approvedBy, approved_at AS approvedAt,
                   executed_at AS executedAt, error_message AS errorMessage,
                   create_time AS createTime
            FROM agent_action
            WHERE run_id = #{runId}
            ORDER BY id ASC
            """)
    List<Map<String, Object>> listAgentRunActions(@Param("runId") Long runId);

    @Select("""
            <script>
            SELECT
                j.id AS jobId,
                j.case_id AS caseId,
                c.case_key AS caseKey,
                c.title AS caseTitle,
                j.document_id AS documentId,
                d.file_name AS fileName,
                d.document_type AS documentType,
                d.parse_status AS parseStatus,
                j.job_type AS jobType,
                j.status,
                j.stage,
                j.progress,
                j.error_message AS errorMessage,
                j.started_at AS startedAt,
                j.finished_at AS finishedAt,
                j.create_time AS createTime,
                j.update_time AS updateTime,
                (SELECT COUNT(*) FROM contract_document_job_trace t WHERE t.job_id = j.id) AS traceCount,
                (SELECT COUNT(*) FROM contract_clause cc WHERE cc.document_id = j.document_id) AS clauseCount,
                (SELECT COUNT(*) FROM contract_clause_chunk ck WHERE ck.document_id = j.document_id) AS chunkCount,
                (SELECT COUNT(*) FROM contract_clause_chunk ck WHERE ck.document_id = j.document_id AND ck.embedding_status = 'DONE') AS embeddedChunkCount,
                (SELECT COUNT(*) FROM contract_clause_chunk ck WHERE ck.document_id = j.document_id AND ck.index_status = 'DONE') AS indexedChunkCount,
                (SELECT COUNT(*) FROM contract_timeline_node n WHERE n.document_id = j.document_id) AS timelineNodeCount,
                (SELECT MAX(r.id) FROM agent_run r WHERE r.subject_type = 'CONTRACT_CASE' AND r.subject_id = j.case_id) AS latestRunId
            FROM contract_document_job j
            JOIN contract_case c ON c.id = j.case_id
            LEFT JOIN contract_document d ON d.id = j.document_id
            WHERE c.deleted = 0
            <if test="status != null and status != ''">
                AND j.status = #{status}
            </if>
            <if test="keyword != null and keyword != ''">
                AND (
                    c.case_key LIKE CONCAT('%', #{keyword}, '%')
                    OR c.title LIKE CONCAT('%', #{keyword}, '%')
                    OR d.file_name LIKE CONCAT('%', #{keyword}, '%')
                    OR j.stage LIKE CONCAT('%', #{keyword}, '%')
                    OR j.error_message LIKE CONCAT('%', #{keyword}, '%')
                )
            </if>
            ORDER BY j.id DESC
            LIMIT #{offset}, #{size}
            </script>
            """)
    List<Map<String, Object>> listDocumentPipelines(@Param("offset") long offset,
                                                    @Param("size") long size,
                                                    @Param("keyword") String keyword,
                                                    @Param("status") String status);

    @Select("""
            <script>
            SELECT COUNT(*)
            FROM contract_document_job j
            JOIN contract_case c ON c.id = j.case_id
            LEFT JOIN contract_document d ON d.id = j.document_id
            WHERE c.deleted = 0
            <if test="status != null and status != ''">
                AND j.status = #{status}
            </if>
            <if test="keyword != null and keyword != ''">
                AND (
                    c.case_key LIKE CONCAT('%', #{keyword}, '%')
                    OR c.title LIKE CONCAT('%', #{keyword}, '%')
                    OR d.file_name LIKE CONCAT('%', #{keyword}, '%')
                    OR j.stage LIKE CONCAT('%', #{keyword}, '%')
                    OR j.error_message LIKE CONCAT('%', #{keyword}, '%')
                )
            </if>
            </script>
            """)
    long countDocumentPipelines(@Param("keyword") String keyword,
                                @Param("status") String status);

    @Select("""
            SELECT
                j.id AS jobId,
                j.case_id AS caseId,
                c.case_key AS caseKey,
                c.title AS caseTitle,
                j.document_id AS documentId,
                d.file_name AS fileName,
                d.document_type AS documentType,
                d.file_size AS fileSize,
                d.version,
                d.parse_status AS parseStatus,
                d.parse_error AS parseError,
                d.page_count AS pageCount,
                j.job_type AS jobType,
                j.status,
                j.stage,
                j.progress,
                j.error_message AS errorMessage,
                j.started_at AS startedAt,
                j.finished_at AS finishedAt,
                j.create_time AS createTime,
                j.update_time AS updateTime,
                (SELECT COUNT(*) FROM contract_clause cc WHERE cc.document_id = j.document_id) AS clauseCount,
                (SELECT COUNT(*) FROM contract_clause_chunk ck WHERE ck.document_id = j.document_id) AS chunkCount,
                (SELECT COUNT(*) FROM contract_clause_chunk ck WHERE ck.document_id = j.document_id AND ck.embedding_status = 'DONE') AS embeddedChunkCount,
                (SELECT COUNT(*) FROM contract_clause_chunk ck WHERE ck.document_id = j.document_id AND ck.index_status = 'DONE') AS indexedChunkCount,
                (SELECT COUNT(*) FROM contract_timeline_node n WHERE n.document_id = j.document_id) AS timelineNodeCount,
                (SELECT MAX(r.id) FROM agent_run r WHERE r.subject_type = 'CONTRACT_CASE' AND r.subject_id = j.case_id) AS latestRunId
            FROM contract_document_job j
            JOIN contract_case c ON c.id = j.case_id
            LEFT JOIN contract_document d ON d.id = j.document_id
            WHERE j.id = #{jobId}
            LIMIT 1
            """)
    Map<String, Object> getDocumentPipeline(@Param("jobId") Long jobId);

    @Select("""
            SELECT id, job_id AS jobId, stage, sequence_no AS sequenceNo,
                   summary, input_json AS inputJson, output_json AS outputJson,
                   error_message AS errorMessage, create_time AS createTime
            FROM contract_document_job_trace
            WHERE job_id = #{jobId}
            ORDER BY sequence_no ASC, id ASC
            """)
    List<Map<String, Object>> listDocumentPipelineTraces(@Param("jobId") Long jobId);
}
