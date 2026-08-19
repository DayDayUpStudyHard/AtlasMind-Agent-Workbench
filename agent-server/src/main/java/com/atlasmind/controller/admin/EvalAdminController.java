package com.atlasmind.controller.admin;

import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.gateway.AiGateway;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
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
    private final ObjectMapper objectMapper;

    // ── Dataset management ─────────────────────────────────────────

    @GetMapping("/datasets")
    public Result<List<Map<String, Object>>> listDatasets() {
        return Result.ok(jdbc.queryForList("""
                SELECT d.id, d.name, d.version, d.description, d.contract_type AS contractType,
                       d.task_purpose AS taskPurpose,
                       d.case_count AS caseCount, d.status, d.create_time AS createTime
                FROM agent_eval_dataset d
                ORDER BY d.create_time DESC
                """).stream().map(this::decorateDataset).toList());
    }

    @PostMapping("/datasets")
    @OperationLog(value = "创建评测数据集", type = "CREATE")
    public Result<Map<String, Object>> createDataset(@RequestBody Map<String, Object> request) {
        String contractType = normalizeDatasetType(str(request, "contractType"));
        jdbc.update("""
                INSERT INTO agent_eval_dataset
                (name, version, description, contract_type, task_purpose, case_count, status)
                VALUES (?,?,?,?,?,0,'DRAFT')
                """,
                str(request, "name"), str(request, "version"),
                str(request, "description"), contractType, str(request, "taskPurpose"));
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
                       scenario, difficulty, noise_level AS noiseLevel,
                       COALESCE(JSON_LENGTH(expected_findings_json), 0) AS expectedFindingCount, status
                FROM agent_eval_case
                WHERE dataset_id=?
                ORDER BY id
                """, datasetId).stream().map(this::decorateCase).toList());
    }

    @GetMapping("/cases/{caseId}")
    public Result<Map<String, Object>> getCase(@PathVariable Long caseId) {
        return Result.ok(decorateCase(first(jdbc.queryForList("""
                SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                       contract_text AS contractText,
                       expected_findings_json AS expectedFindingsJson,
                       should_not_find_json AS shouldNotFindJson,
                       expected_citation_count AS expectedCitationCount,
                       scenario, industry, difficulty,
                       noise_level AS noiseLevel,
                       must_have_contract_citation AS mustHaveContractCitation,
                       must_have_policy_citation AS mustHavePolicyCitation,
                       fulfillment_evidence_json AS fulfillmentEvidenceJson,
                       target_timeline_selector_json AS targetTimelineSelectorJson,
                       expected_judgements_json AS expectedJudgementsJson,
                       expected_manual_result AS expectedManualResult,
                       dataset_id AS datasetId, status
                FROM agent_eval_case WHERE id=?""", caseId))));
    }

    @PostMapping("/datasets/{datasetId}/cases")
    @OperationLog(value = "添加评测用例", type = "CREATE")
    public Result<Map<String, Object>> addCase(@PathVariable Long datasetId,
                                                @RequestBody Map<String, Object> request) {
        String contractType = normalizeCaseType(str(request, "contractType"));
        jdbc.update("""
                INSERT INTO agent_eval_case
                (dataset_id, case_key, title, contract_type, contract_text,
                 expected_findings_json, should_not_find_json, expected_citation_count,
                 scenario, industry, difficulty, noise_level,
                 must_have_contract_citation, must_have_policy_citation,
                 fulfillment_evidence_json, target_timeline_selector_json,
                 expected_judgements_json, expected_manual_result, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE')
                """,
                datasetId, str(request, "caseKey"), str(request, "title"),
                contractType, str(request, "contractText"),
                str(request, "expectedFindingsJson"), str(request, "shouldNotFindJson"),
                request.getOrDefault("expectedCitationCount", 0),
                str(request, "scenario"), str(request, "industry"),
                str(request, "difficulty"), str(request, "noiseLevel"),
                request.getOrDefault("mustHaveContractCitation", 0),
                request.getOrDefault("mustHavePolicyCitation", 0),
                str(request, "fulfillmentEvidenceJson"),
                str(request, "targetTimelineSelectorJson"),
                str(request, "expectedJudgementsJson"),
                str(request, "expectedManualResult"));
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
        String runtime = str(request, "runtime"); // legacy | langgraph | langgraph_v2
        if (!Set.of("legacy", "langgraph", "langgraph_v2")
                .contains(runtime.toLowerCase(Locale.ROOT))) {
            throw new IllegalArgumentException(
                    "未知运行时引擎: " + runtime + "（支持 legacy / langgraph / langgraph_v2）");
        }
        String featuresJson = str(request, "features");
        if (featuresJson.isEmpty()) featuresJson = "{}";
        if ("legacy".equalsIgnoreCase(runtime)) {
            // The legacy pipeline cannot produce extraction/timeline artifacts.
            // Reject up front instead of failing every case at runtime.
            String datasetType = jdbc.queryForObject(
                    "SELECT contract_type FROM agent_eval_dataset WHERE id=?",
                    String.class, datasetId);
            String legacyTask = normalizeLegacyTask(datasetType);
            if (!Set.of("CONTRACT_REVIEW", "COMPREHENSIVE")
                    .contains(legacyTask)) {
                throw new IllegalArgumentException(
                        "传统流水线引擎不支持该数据集的任务类型（" + legacyTask + "），请改用 LangGraph 引擎");
            }
        }
        Integer activeCount = jdbc.queryForObject("""
                SELECT COUNT(*) FROM agent_eval_run
                WHERE dataset_id=?
                  AND status IN ('QUEUED','PRECHECKING','RUNNING')
                """, Integer.class, datasetId);
        if (activeCount != null && activeCount > 0) {
            throw new IllegalArgumentException("该数据集已有评测在排队或运行中");
        }

        jdbc.update("""
                INSERT INTO agent_eval_run
                (dataset_id, runtime_engine, features_json, status, started_at)
                VALUES (?,?,?,'QUEUED',NOW())
                """,
                datasetId, runtime, featuresJson);

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
                       d.contract_type AS contractType,
                       r.runtime_engine AS runtimeEngine, r.graph_name AS graphName,
                       r.graph_version AS graphVersion, r.status,
                       r.high_risk_recall AS highRiskRecall,
                       r.dual_citation_rate AS dualCitationRate,
                       r.false_positive_rate AS falsePositiveRate,
                       r.case_count AS caseCount, r.passed_count AS passedCount,
                       r.features_json AS featuresJson,
                       r.current_case_index AS currentCaseIndex,
                       r.current_case_key AS currentCaseKey,
                       r.current_step AS currentStep,
                       r.queue_position AS queuePosition,
                       r.environment_status AS environmentStatus,
                       r.environment_snapshot_json AS environmentSnapshotJson,
                       r.is_production_baseline AS isProductionBaseline,
                       r.promoted_at AS promotedAt,
                       r.summary_json AS summaryJson,
                       r.started_at AS startedAt, r.finished_at AS finishedAt
                FROM agent_eval_run r
                JOIN agent_eval_dataset d ON d.id=r.dataset_id
                ORDER BY r.id DESC LIMIT 50
                """).stream().map(this::decorateRun).toList());
    }

    // ── Version comparison board (PRD Phase 8 task 7) ──────────────
    // v1 基线（legacy）/ 迁移版本（graph）对照：按运行时 + 图 + 模型 + 提示词
    // 版本聚合已完成评测的指标，作为「迁移前后指标可追溯」的看板数据源。

    @GetMapping("/versions/comparison")
    public Result<List<Map<String, Object>>> versionComparison() {
        return Result.ok(jdbc.queryForList("""
                SELECT
                       COALESCE(NULLIF(r.graph_name, ''), CONCAT('legacy-', r.runtime_engine)) AS versionKey,
                       r.runtime_engine AS runtimeEngine,
                       r.graph_name AS graphName,
                       r.graph_version AS graphVersion,
                       r.llm_model AS llmModel,
                       r.prompt_version AS promptVersion,
                       COUNT(*) AS runCount,
                       ROUND(AVG(r.high_risk_recall), 4) AS avgHighRiskRecall,
                       ROUND(AVG(r.dual_citation_rate), 4) AS avgDualCitationRate,
                       ROUND(AVG(r.false_positive_rate), 4) AS avgFalsePositiveRate,
                       ROUND(AVG(r.schema_valid_rate), 4) AS avgSchemaValidRate,
                       MAX(r.finished_at) AS lastFinishedAt
                FROM agent_eval_run r
                WHERE r.status = 'COMPLETED'
                GROUP BY versionKey, r.runtime_engine, r.graph_name, r.graph_version,
                         r.llm_model, r.prompt_version
                ORDER BY MAX(r.finished_at) DESC
                """).stream().map(row -> {
            row.put("versionLabel", versionLabel(row));
            return row;
        }).toList());
    }

    private String versionLabel(Map<String, Object> row) {
        String graphName = str(row, "graphName");
        String graphVersion = str(row, "graphVersion");
        if (!graphName.isEmpty()) {
            return graphName + " @ " + graphVersion;
        }
        return "v1 基线（legacy " + str(row, "runtimeEngine") + "）";
    }

    @DeleteMapping("/runs/{runId}")
    @OperationLog(value = "删除评测记录", type = "DELETE")
    public Result<Map<String, Object>> deleteRun(@PathVariable Long runId) {
        jdbc.update("DELETE FROM agent_eval_result WHERE run_id=?", runId);
        jdbc.update("DELETE FROM agent_eval_run WHERE id=?", runId);
        return Result.ok(Map.of("deleted", true));
    }

    @GetMapping("/runs/{runId}")
    public Result<Map<String, Object>> getRun(@PathVariable Long runId) {
        Map<String, Object> run = first(jdbc.queryForList("""
                SELECT r.id, r.dataset_id AS datasetId, d.name AS datasetName, d.version AS datasetVersion,
                       d.contract_type AS contractType,
                       r.runtime_engine AS runtimeEngine, r.graph_name AS graphName,
                       r.graph_version AS graphVersion, r.llm_model AS llmModel,
                       r.prompt_version AS promptVersion, r.status,
                       r.high_risk_recall AS highRiskRecall,
                       r.dual_citation_rate AS dualCitationRate,
                       r.false_positive_rate AS falsePositiveRate,
                       r.schema_valid_rate AS schemaValidRate,
                       r.case_count AS caseCount, r.passed_count AS passedCount,
                       r.summary_json AS summaryJson,
                       r.features_json AS featuresJson,
                       r.current_case_index AS currentCaseIndex,
                       r.current_case_key AS currentCaseKey,
                       r.current_step AS currentStep,
                       r.queue_position AS queuePosition,
                       r.environment_status AS environmentStatus,
                       r.environment_snapshot_json AS environmentSnapshotJson,
                       r.is_production_baseline AS isProductionBaseline,
                       r.promoted_at AS promotedAt,
                       r.started_at AS startedAt, r.finished_at AS finishedAt,
                       r.create_time AS createTime
                FROM agent_eval_run r
                JOIN agent_eval_dataset d ON d.id=r.dataset_id
                WHERE r.id=?
                """, runId));
        if (run == null) throw new IllegalArgumentException("评测运行不存在");

        List<Map<String, Object>> results = jdbc.queryForList("""
                SELECT er.id, er.run_id AS runId, er.case_id AS caseId,
                       er.success, er.high_recall AS highRecall,
                       er.dual_citation_rate AS dualCitationRate,
                       er.false_positives AS falsePositives,
                       er.analysis_mode AS analysisMode,
                       er.risk_score AS riskScore,
                       er.finding_count AS findingCount,
                       er.error_message AS errorMessage,
                       er.result_json AS resultJson,
                       er.schema_valid_rate AS schemaValidRate,
                       er.create_time AS createTime,
                       ec.case_key AS caseKey, ec.title AS caseTitle,
                       ec.scenario, ec.industry, ec.difficulty,
                       ec.noise_level AS noiseLevel,
                       ec.expected_findings_json AS expectedFindingsJson,
                       ec.should_not_find_json AS shouldNotFindJson
                FROM agent_eval_result er
                JOIN agent_eval_case ec ON ec.id=er.case_id
                WHERE er.run_id=?
                ORDER BY ec.id
                """, runId);
        run.put("results", results.stream().map(this::decorateResult).toList());
        decorateRun(run);
        return Result.ok(run);
    }

    @PostMapping("/runs/{runId}/promote")
    @Transactional
    @OperationLog(value = "设置评测运行生产基线", type = "UPDATE")
    public Result<Map<String, Object>> promoteRun(@PathVariable Long runId) {
        Map<String, Object> run = first(jdbc.queryForList(
                "SELECT id, dataset_id AS datasetId, status, summary_json AS summaryJson "
                        + "FROM agent_eval_run WHERE id=? FOR UPDATE", runId));
        if (run == null) throw new IllegalArgumentException("评测运行不存在");
        if (!"COMPLETED".equalsIgnoreCase(str(run, "status"))) {
            throw new IllegalStateException("只有 COMPLETED 评测运行可以设为生产基线");
        }
        if (!"PASSED".equalsIgnoreCase(releaseGateStatus(run.get("summaryJson")))) {
            throw new IllegalStateException("评测发布门禁未通过，不能设为生产基线");
        }

        Long datasetId = numberAsLong(run.get("datasetId"));
        jdbc.update("UPDATE agent_eval_run SET is_production_baseline=0 "
                + "WHERE dataset_id=? AND is_production_baseline=1", datasetId);
        jdbc.update("UPDATE agent_eval_run SET is_production_baseline=1, promoted_at=NOW() "
                + "WHERE id=?", runId);
        return Result.ok(Map.of(
                "promoted", true,
                "runId", runId,
                "datasetId", datasetId,
                "message", "评测运行已设为该数据集的生产基线"));
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
                "diffs", diffs.stream().map(this::decorateDiff).toList()));
    }

    @GetMapping("/metrics/trend")
    public Result<List<Map<String, Object>>> metricsTrend() {
        return Result.ok(jdbc.queryForList("""
                SELECT r.id, d.name AS datasetName, r.runtime_engine AS runtimeEngine,
                       d.contract_type AS contractType,
                       r.status, r.high_risk_recall AS highRiskRecall,
                       r.dual_citation_rate AS dualCitationRate,
                       r.false_positive_rate AS falsePositiveRate,
                       r.started_at AS startedAt
                FROM agent_eval_run r
                JOIN agent_eval_dataset d ON d.id=r.dataset_id
                WHERE r.status='COMPLETED'
                ORDER BY r.started_at DESC LIMIT 20
                """).stream().map(this::decorateRun).toList());
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

    private String releaseGateStatus(Object rawSummary) {
        if (rawSummary == null) return "";
        try {
            return objectMapper.readTree(rawSummary.toString())
                    .path("releaseGate").path("status").asText("");
        } catch (Exception ignored) {
            return "";
        }
    }

    private static Map<String, Object> first(List<Map<String, Object>> list) {
        return list.isEmpty() ? null : list.get(0);
    }

    private Map<String, Object> decorateDataset(Map<String, Object> row) {
        if (row == null) return null;
        row.put("contractTypeLabel", datasetTypeLabel(str(row, "contractType")));
        row.put("statusLabel", statusLabel(str(row, "status")));
        return row;
    }

    private Map<String, Object> decorateCase(Map<String, Object> row) {
        if (row == null) return null;
        row.put("contractTypeLabel", caseTypeLabel(str(row, "contractType")));
        row.put("statusLabel", statusLabel(str(row, "status")));
        return row;
    }

    private Map<String, Object> decorateRun(Map<String, Object> row) {
        if (row == null) return null;
        row.put("runtimeEngineLabel", runtimeLabel(str(row, "runtimeEngine")));
        // 实际执行的引擎由 Python 端写入 summary_json（防止旧 API 进程
        // 静默回退 legacy 时界面仍显示请求的引擎，2026-08-14 事故）。
        String actualEngine = "";
        boolean mismatch = false;
        String summaryJson = str(row, "summaryJson");
        if (!summaryJson.isEmpty() && !"{}".equals(summaryJson)) {
            try {
                Map<String, Object> summary = objectMapper.readValue(
                        summaryJson, new TypeReference<Map<String, Object>>() {});
                Object actual = summary.get("actualRuntimeEngine");
                Object mismatchFlag = summary.get("runtimeEngineMismatch");
                actualEngine = actual == null ? "" : actual.toString().trim();
                mismatch = Boolean.TRUE.equals(mismatchFlag);
                Object operations = summary.get("operations");
                if (operations instanceof Map<?, ?> operationMap) {
                    row.put("operations", operationMap);
                    row.put("latencyP50Ms", operationMap.get("latencyP50Ms"));
                    row.put("latencyP95Ms", operationMap.get("latencyP95Ms"));
                    row.put("tokenInputTotal", operationMap.get("tokenInputTotal"));
                    row.put("tokenOutputTotal", operationMap.get("tokenOutputTotal"));
                    row.put("estimatedCost", operationMap.get("estimatedCost"));
                    row.put("costCurrency", operationMap.get("costCurrency"));
                    row.put("costStatus", operationMap.get("costStatus"));
                    row.put("executionStack", operationMap.get("executionStack"));
                }
            } catch (Exception ignored) {
                // summary_json 无法解析时按无信息处理
            }
        }
        row.put("actualRuntimeEngine", actualEngine);
        row.put("actualRuntimeEngineLabel",
                actualEngine.isEmpty() ? "" : actualEngineLabel(actualEngine));
        row.put("runtimeEngineMismatch", mismatch);
        row.put("datasetTypeLabel", datasetTypeLabel(str(row, "contractType")));
        row.put("statusLabel", statusLabel(str(row, "status")));
        return row;
    }

    private Map<String, Object> decorateResult(Map<String, Object> row) {
        if (row == null) return null;
        row.put("analysisModeLabel", analysisModeLabel(str(row, "analysisMode")));
        return row;
    }

    private Map<String, Object> decorateDiff(Map<String, Object> row) {
        if (row == null) return null;
        row.put("mode1Label", analysisModeLabel(str(row, "mode1")));
        row.put("mode2Label", analysisModeLabel(str(row, "mode2")));
        return row;
    }

    private static String normalizeDatasetType(String value) {
        String v = value == null ? "" : value.trim().toUpperCase(Locale.ROOT);
        if (v.isBlank()) return "CONTRACT_REVIEW";
        return switch (v) {
            case "CONTRACT_REVIEW", "RISK_REVIEW" -> "CONTRACT_REVIEW";
            case "INTAKE", "ELEMENT_EXTRACTION" -> "INTAKE";
            case "FULFILLMENT_TIMELINE", "TIMELINE_EXTRACTION" -> "FULFILLMENT_TIMELINE";
            case "FULFILLMENT_CHECK", "FULFILLMENT_VERIFICATION" -> "FULFILLMENT_CHECK";
            case "COMPREHENSIVE" -> "COMPREHENSIVE";
            default -> "CONTRACT_REVIEW";
        };
    }

    private static String normalizeLegacyTask(String value) {
        String v = value == null ? "" : value.trim().toUpperCase(Locale.ROOT);
        if (v.isBlank()) return "CONTRACT_REVIEW";
        // Mirror the Python legacy worker's _eval_task_type mapping.
        return switch (v) {
            case "INTAKE", "ELEMENT_EXTRACTION", "CONTRACT_ELEMENT_EXTRACTION" -> "CONTRACT_ELEMENT_EXTRACTION";
            case "FULFILLMENT_TIMELINE", "TIMELINE_EXTRACTION" -> "TIMELINE_EXTRACTION";
            case "RISK_REVIEW" -> "CONTRACT_REVIEW";
            default -> v;
        };
    }

    private static String normalizeCaseType(String value) {
        String v = value == null ? "" : value.trim().toUpperCase(Locale.ROOT);
        if (v.isBlank()) return "OTHER";
        // Seed data and the admin UI send GOODS_PROCUREMENT; canonical token is GOODS_PURCHASE.
        v = "GOODS_PROCUREMENT".equals(v) ? "GOODS_PURCHASE" : v;
        return Set.of("SERVICE_PROCUREMENT", "GOODS_PURCHASE", "NDA", "OTHER",
                "ENGINEERING_EPC", "SOFTWARE_IT", "OPS_MAINTENANCE", "MIXED").contains(v) ? v : "OTHER";
    }

    private static String datasetTypeLabel(String value) {
        return switch (value == null ? "" : value.trim().toUpperCase(Locale.ROOT)) {
            case "CONTRACT_REVIEW", "RISK_REVIEW" -> "风险审查";
            case "INTAKE", "ELEMENT_EXTRACTION" -> "合同要素提取";
            case "FULFILLMENT_TIMELINE", "TIMELINE_EXTRACTION" -> "履约日程提取";
            case "FULFILLMENT_CHECK", "FULFILLMENT_VERIFICATION" -> "履约核验";
            case "COMPREHENSIVE" -> "综合评测";
            default -> "风险审查";
        };
    }

    private static String caseTypeLabel(String value) {
        return switch (value == null ? "" : value.trim().toUpperCase(Locale.ROOT)) {
            case "SERVICE_PROCUREMENT" -> "服务采购";
            case "GOODS_PURCHASE" -> "货物采购";
            case "NDA" -> "保密协议";
            case "ENGINEERING_EPC" -> "工程EPC";
            case "SOFTWARE_IT" -> "软件IT";
            case "OPS_MAINTENANCE" -> "运维服务";
            case "MIXED" -> "混合场景";
            default -> "其他";
        };
    }

    private static String runtimeLabel(String value) {
        return switch (value == null ? "" : value.trim().toLowerCase(Locale.ROOT)) {
            case "langgraph" -> "LangGraph";
            case "langgraph_v2" -> "LangGraph v2（试点）";
            case "legacy" -> "传统流水线";
            default -> value == null || value.isBlank() ? "-" : value;
        };
    }

    /** 实际执行引擎标签，值为 "langgraph/图名/版本" 或 "legacy"（由 Python summary 写入）。 */
    private static String actualEngineLabel(String value) {
        String[] parts = value.split("/");
        return switch (parts[0]) {
            case "legacy" -> "传统流水线（Legacy）";
            case "langgraph" -> parts.length >= 3
                    ? "LangGraph " + parts[2] + "（" + parts[1] + "）"
                    : "LangGraph";
            default -> value;
        };
    }

    private static String statusLabel(String value) {
        return switch (value == null ? "" : value.trim().toUpperCase(Locale.ROOT)) {
            case "ACTIVE" -> "启用";
            case "DRAFT" -> "草稿";
            case "QUEUED" -> "排队中";
            case "PRECHECKING" -> "环境检查";
            case "RUNNING" -> "运行中";
            case "ENVIRONMENT_UNAVAILABLE" -> "环境不可用";
            case "COMPLETED" -> "已完成";
            case "DEGRADED" -> "结果降级";
            case "FAILED" -> "失败";
            case "CANCELLED" -> "已取消";
            default -> value == null || value.isBlank() ? "-" : value;
        };
    }

    private static String analysisModeLabel(String value) {
        return switch (value == null ? "" : value.trim().toUpperCase(Locale.ROOT)) {
            case "FULL" -> "完整分析";
            case "LIMITED" -> "范围受限";
            case "RULE_ONLY" -> "规则兜底";
            case "INFRA_FAILED" -> "环境失败";
            default -> value == null || value.isBlank() ? "-" : value;
        };
    }
}
