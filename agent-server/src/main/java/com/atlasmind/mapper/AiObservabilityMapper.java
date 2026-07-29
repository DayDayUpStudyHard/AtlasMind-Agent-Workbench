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
}
