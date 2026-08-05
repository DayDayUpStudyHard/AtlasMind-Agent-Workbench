package com.atlasmind.controller.admin;

import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.gateway.AiGateway;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import java.util.*;

/**
 * Evaluation center — manage datasets, run evaluations, compare results.
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/eval")
public class EvalAdminController {

    private final JdbcTemplate jdbc;
    private final AiGateway aiGateway;

    // ── Dataset management ─────────────────────────────────────────

    @GetMapping("/datasets")
    public Result<List<Map<String, Object>>> listDatasets() {
        return Result.ok(jdbc.queryForList("""
                SELECT d.id, d.name, d.version, d.description, d.contract_type AS contractType,
                       d.case_count AS caseCount, d.status, d.create_time AS createTime
                FROM agent_eval_dataset d
                ORDER BY d.create_time DESC
                """));
    }

    @PostMapping("/datasets")
    @OperationLog(value = "创建评测数据集", type = "CREATE")
    public Result<Map<String, Object>> createDataset(@RequestBody Map<String, Object> request) {
        jdbc.update("""
                INSERT INTO agent_eval_dataset (name, version, description, contract_type, case_count, status)
                VALUES (?,?,?,?,0,'DRAFT')
                """,
                str(request, "name"), str(request, "version"),
                str(request, "description"), str(request, "contractType"));
        return Result.ok(Map.of("created", true));
    }

    @DeleteMapping("/datasets/{id}")
    @OperationLog(value = "删除评测数据集", type = "DELETE")
    public Result<Map<String, Object>> deleteDataset(@PathVariable Long id) {
        jdbc.update("DELETE FROM agent_eval_case WHERE dataset_id=?", id);
        jdbc.update("DELETE FROM agent_eval_dataset WHERE id=?", id);
        return Result.ok(Map.of("deleted", true));
    }

    // ── Case management ────────────────────────────────────────────

    @GetMapping("/datasets/{datasetId}/cases")
    public Result<List<Map<String, Object>>> listCases(@PathVariable Long datasetId) {
        return Result.ok(jdbc.queryForList("""
                SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                       COALESCE(JSON_LENGTH(expected_findings_json), 0) AS expectedFindingCount, status
                FROM agent_eval_case
                WHERE dataset_id=?
                ORDER BY id
                """, datasetId));
    }

    @GetMapping("/cases/{caseId}")
    public Result<Map<String, Object>> getCase(@PathVariable Long caseId) {
        return Result.ok(first(jdbc.queryForList(
                "SELECT * FROM agent_eval_case WHERE id=?", caseId)));
    }

    @PostMapping("/datasets/{datasetId}/cases")
    @OperationLog(value = "添加评测用例", type = "CREATE")
    public Result<Map<String, Object>> addCase(@PathVariable Long datasetId,
                                                @RequestBody Map<String, Object> request) {
        jdbc.update("""
                INSERT INTO agent_eval_case
                (dataset_id, case_key, title, contract_type, contract_text,
                 expected_findings_json, should_not_find_json, expected_citation_count, status)
                VALUES (?,?,?,?,?,?,?,?,'ACTIVE')
                """,
                datasetId, str(request, "caseKey"), str(request, "title"),
                str(request, "contractType"), str(request, "contractText"),
                str(request, "expectedFindingsJson"), str(request, "shouldNotFindJson"),
                request.getOrDefault("expectedCitationCount", 0));
        jdbc.update("""
                UPDATE agent_eval_dataset
                SET case_count=(SELECT COUNT(*) FROM agent_eval_case WHERE dataset_id=?)
                WHERE id=?
                """, datasetId, datasetId);
        return Result.ok(Map.of("added", true));
    }

    @DeleteMapping("/cases/{caseId}")
    @OperationLog(value = "删除评测用例", type = "DELETE")
    public Result<Map<String, Object>> deleteCase(@PathVariable Long caseId) {
        Long datasetId = jdbc.queryForObject(
                "SELECT dataset_id FROM agent_eval_case WHERE id=?", Long.class, caseId);
        jdbc.update("DELETE FROM agent_eval_case WHERE id=?", caseId);
        if (datasetId != null) {
            jdbc.update("""
                    UPDATE agent_eval_dataset
                    SET case_count=(SELECT COUNT(*) FROM agent_eval_case WHERE dataset_id=?)
                    WHERE id=?
                    """, datasetId, datasetId);
        }
        return Result.ok(Map.of("deleted", true));
    }

    // ── Eval runs ──────────────────────────────────────────────────

    @PostMapping("/runs")
    @OperationLog(value = "发起评测运行", type = "CREATE")
    public Result<Map<String, Object>> startEvalRun(@RequestBody Map<String, Object> request) {
        Long datasetId = numberAsLong(request.get("datasetId"));
        String runtime = str(request, "runtime"); // legacy | langgraph

        jdbc.update("""
                INSERT INTO agent_eval_run
                (dataset_id, runtime_engine, graph_name, graph_version,
                 llm_model, prompt_version, status, started_at)
                VALUES (?,?,?,?,?,?,'RUNNING',NOW())
                """,
                datasetId, runtime,
                str(request, "graphName"), str(request, "graphVersion"),
                str(request, "llmModel"), str(request, "promptVersion"));

        // Get the generated eval_run_id
        Long evalRunId = jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);

        // Trigger async Python eval
        try {
            aiGateway.runEvaluation(evalRunId);
        } catch (Exception e) {
            jdbc.update("UPDATE agent_eval_run SET status='FAILED', summary_json=? WHERE id=?",
                    "{\"error\": \"" + e.getMessage() + "\"}", evalRunId);
        }

        return Result.ok(Map.of(
                "started", true,
                "evalRunId", evalRunId,
                "message", "评测任务已创建并提交 Python 执行"));
    }

    @GetMapping("/runs")
    public Result<List<Map<String, Object>>> listRuns() {
        return Result.ok(jdbc.queryForList("""
                SELECT r.id, d.name AS datasetName, d.version AS datasetVersion,
                       r.runtime_engine AS runtimeEngine, r.graph_name AS graphName,
                       r.graph_version AS graphVersion, r.status,
                       r.high_risk_recall AS highRiskRecall,
                       r.dual_citation_rate AS dualCitationRate,
                       r.false_positive_rate AS falsePositiveRate,
                       r.case_count AS caseCount, r.passed_count AS passedCount,
                       r.started_at AS startedAt, r.finished_at AS finishedAt
                FROM agent_eval_run r
                JOIN agent_eval_dataset d ON d.id=r.dataset_id
                ORDER BY r.id DESC LIMIT 50
                """));
    }

    @GetMapping("/runs/{runId}")
    public Result<Map<String, Object>> getRun(@PathVariable Long runId) {
        Map<String, Object> run = first(jdbc.queryForList("""
                SELECT r.*, d.name AS datasetName, d.version AS datasetVersion
                FROM agent_eval_run r
                JOIN agent_eval_dataset d ON d.id=r.dataset_id
                WHERE r.id=?
                """, runId));
        if (run == null) throw new IllegalArgumentException("评测运行不存在");

        List<Map<String, Object>> results = jdbc.queryForList("""
                SELECT er.*, ec.title AS caseTitle, ec.case_key AS caseKey
                FROM agent_eval_result er
                JOIN agent_eval_case ec ON ec.id=er.case_id
                WHERE er.run_id=?
                ORDER BY ec.id
                """, runId);
        run.put("results", results);
        return Result.ok(run);
    }

    @GetMapping("/runs/compare")
    public Result<Map<String, Object>> compareRuns(
            @RequestParam Long runId1,
            @RequestParam Long runId2) {
        Map<String, Object> run1 = first(jdbc.queryForList(
                "SELECT * FROM agent_eval_run WHERE id=?", runId1));
        Map<String, Object> run2 = first(jdbc.queryForList(
                "SELECT * FROM agent_eval_run WHERE id=?", runId2));
        if (run1 == null || run2 == null) throw new IllegalArgumentException("评测运行不存在");

        List<Map<String, Object>> diffs = jdbc.queryForList("""
                SELECT r1.case_id AS caseId, ec.title AS caseTitle,
                       r1.high_recall AS recall1, r2.high_recall AS recall2,
                       r1.dual_citation_rate AS dualCite1, r2.dual_citation_rate AS dualCite2,
                       r1.analysis_mode AS mode1, r2.analysis_mode AS mode2,
                       r1.risk_score AS score1, r2.risk_score AS score2
                FROM agent_eval_result r1
                JOIN agent_eval_result r2 ON r2.case_id=r1.case_id AND r2.run_id=?
                JOIN agent_eval_case ec ON ec.id=r1.case_id
                WHERE r1.run_id=?
                ORDER BY ec.id
                """, runId2, runId1);

        return Result.ok(Map.of(
                "run1", run1,
                "run2", run2,
                "diffs", diffs));
    }

    @GetMapping("/metrics/trend")
    public Result<List<Map<String, Object>>> metricsTrend() {
        return Result.ok(jdbc.queryForList("""
                SELECT r.id, d.name AS datasetName, r.runtime_engine AS runtimeEngine,
                       r.status, r.high_risk_recall AS highRiskRecall,
                       r.dual_citation_rate AS dualCitationRate,
                       r.false_positive_rate AS falsePositiveRate,
                       r.started_at AS startedAt
                FROM agent_eval_run r
                JOIN agent_eval_dataset d ON d.id=r.dataset_id
                WHERE r.status='COMPLETED'
                ORDER BY r.started_at DESC LIMIT 20
                """));
    }

    // ── helpers ────────────────────────────────────────────────────

    private static String str(Map<String, Object> map, String key) {
        Object value = map.getOrDefault(key, "");
        return value == null ? "" : value.toString().trim();
    }

    private static Long numberAsLong(Object value) {
        if (value instanceof Number n) return n.longValue();
        if (value instanceof String s) {
            try { return Long.parseLong(s.trim()); } catch (NumberFormatException e) { return 0L; }
        }
        return 0L;
    }

    private static Map<String, Object> first(List<Map<String, Object>> list) {
        return list.isEmpty() ? null : list.get(0);
    }
}
