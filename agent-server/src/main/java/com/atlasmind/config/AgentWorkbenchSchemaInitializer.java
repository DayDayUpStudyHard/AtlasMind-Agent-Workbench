package com.atlasmind.config;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.core.annotation.Order;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

/**
 * 增量初始化 Agent 工作台表，保证已有 AtlasMind 本地数据库可以直接升级。
 */
@Component
@Order(0)
public class AgentWorkbenchSchemaInitializer implements CommandLineRunner {

    private final JdbcTemplate jdbcTemplate;

    public AgentWorkbenchSchemaInitializer(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public void run(String... args) {
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS agent_project (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(160) NOT NULL,
                    project_key VARCHAR(60) NOT NULL,
                    description VARCHAR(1000),
                    repository_type VARCHAR(30) NOT NULL DEFAULT 'GITHUB',
                    repository_url VARCHAR(500),
                    default_branch VARCHAR(120) DEFAULT 'main',
                    business_scope VARCHAR(1000),
                    release_target VARCHAR(120),
                    current_milestone VARCHAR(200),
                    team_size INT,
                    tech_stack VARCHAR(500),
                    health_status VARCHAR(30) DEFAULT 'UNKNOWN',
                    health_score INT DEFAULT 0,
                    last_run_id BIGINT,
                    last_run_at DATETIME,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    deleted TINYINT DEFAULT 0,
                    UNIQUE KEY uk_project_key (project_key),
                    KEY idx_project_status (health_status, deleted)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS project_source (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    project_id BIGINT NOT NULL,
                    source_type VARCHAR(30) NOT NULL DEFAULT 'GITHUB',
                    source_url VARCHAR(500) NOT NULL,
                    default_branch VARCHAR(120) DEFAULT 'main',
                    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                    last_sync_job_id BIGINT,
                    last_sync_at DATETIME,
                    last_error TEXT,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_project_source_url (project_id, source_url),
                    KEY idx_project_source (project_id, status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS project_sync_job (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    project_id BIGINT NOT NULL,
                    source_id BIGINT,
                    sync_type VARCHAR(30) NOT NULL DEFAULT 'MANUAL',
                    status VARCHAR(30) NOT NULL DEFAULT 'RUNNING',
                    progress INT DEFAULT 0,
                    message VARCHAR(500),
                    counters_json LONGTEXT,
                    error_message TEXT,
                    started_at DATETIME,
                    finished_at DATETIME,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    KEY idx_project_sync_job (project_id, create_time),
                    KEY idx_sync_job_status (status, create_time)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS project_evidence (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    project_id BIGINT NOT NULL,
                    source_id BIGINT,
                    source_type VARCHAR(30) NOT NULL DEFAULT 'GITHUB',
                    object_type VARCHAR(40) NOT NULL,
                    title VARCHAR(260) NOT NULL,
                    source_ref VARCHAR(260),
                    source_url VARCHAR(700),
                    content_snippet TEXT,
                    raw_json LONGTEXT,
                    evidence_hash VARCHAR(64) NOT NULL,
                    confidence_score DECIMAL(5,4) DEFAULT 0.8000,
                    observed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_project_evidence_hash (project_id, evidence_hash),
                    KEY idx_project_evidence_type (project_id, object_type, update_time),
                    KEY idx_project_evidence_source (source_id, object_type)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS agent_action (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    project_id BIGINT NOT NULL,
                    run_id BIGINT NOT NULL,
                    action_type VARCHAR(50) NOT NULL,
                    status VARCHAR(30) NOT NULL DEFAULT 'PENDING_APPROVAL',
                    title VARCHAR(240) NOT NULL,
                    payload_json LONGTEXT,
                    external_id VARCHAR(120),
                    approved_by VARCHAR(100),
                    approved_at DATETIME,
                    executed_at DATETIME,
                    result_json LONGTEXT,
                    error_message TEXT,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    KEY idx_run_action (run_id, status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS project_kb_document (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    project_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    usage_type VARCHAR(40) NOT NULL DEFAULT 'ANALYSIS_CONTEXT',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_project_kb_document (project_id, document_id),
                    KEY idx_kb_document_project (document_id, project_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        addColumnIfMissing("kb_document", "contract_usage_scope",
                "VARCHAR(32) NOT NULL DEFAULT 'DISABLED'");
        addColumnIfMissing("kb_document", "contract_usage_summary", "VARCHAR(256)");
        addColumnIfMissing("kb_document", "contract_usage_updated_at",
                "DATETIME DEFAULT CURRENT_TIMESTAMP");
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_kb_document (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    usage_type VARCHAR(40) NOT NULL DEFAULT 'CONTRACT_AGENT_CONTEXT',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_contract_kb_document (case_id, document_id),
                    KEY idx_contract_kb_document (document_id, case_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS system_config (
                    config_key VARCHAR(64) PRIMARY KEY,
                    config_value VARCHAR(256) NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_document_job (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    job_type VARCHAR(64) NOT NULL DEFAULT 'CONTRACT_DOCUMENT_PIPELINE',
                    status VARCHAR(64) NOT NULL DEFAULT 'UPLOADED',
                    stage VARCHAR(64),
                    progress INT NOT NULL DEFAULT 0,
                    error_message TEXT,
                    started_at DATETIME,
                    finished_at DATETIME,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    KEY idx_case_job (case_id, create_time),
                    KEY idx_document_job (document_id, create_time),
                    KEY idx_status (status, create_time)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        addColumnIfMissing("contract_case", "signed_date", "DATE");
        addColumnIfMissing("contract_case", "our_side", "VARCHAR(8)");
        addColumnIfMissing("contract_document", "parse_provider", "VARCHAR(128)");
        addColumnIfMissing("contract_document", "parse_quality", "VARCHAR(32)");
        addColumnIfMissing("contract_document", "parse_diagnostics_json", "LONGTEXT");
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_document_job_trace (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    job_id BIGINT NOT NULL,
                    stage VARCHAR(64) NOT NULL,
                    sequence_no INT NOT NULL,
                    summary VARCHAR(500) NOT NULL,
                    input_json LONGTEXT,
                    output_json LONGTEXT,
                    error_message TEXT,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_job_seq (job_id, sequence_no),
                    KEY idx_job_stage (job_id, stage, sequence_no)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_clause_chunk (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    clause_id BIGINT,
                    clause_number VARCHAR(64),
                    chunk_index INT NOT NULL,
                    chunk_text LONGTEXT NOT NULL,
                    source_page INT,
                    content_hash CHAR(64) NOT NULL,
                    embedding_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                    index_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    KEY idx_case_chunk (case_id, document_id, chunk_index),
                    KEY idx_clause_chunk (clause_id, chunk_index),
                    KEY idx_embedding_status (embedding_status, index_status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_timeline_node (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    document_id BIGINT,
                    clause_id BIGINT,
                    node_type VARCHAR(64) NOT NULL,
                    label VARCHAR(256) NOT NULL,
                    node_date DATE,
                    condition_text VARCHAR(512),
                    responsible_party VARCHAR(64),
                    business_meaning TEXT,
                    citation_json LONGTEXT,
                    confidence DECIMAL(5,4),
                    source VARCHAR(64) NOT NULL DEFAULT 'EXTRACTED',
                    status VARCHAR(64) NOT NULL DEFAULT 'EXTRACTED',
                    manual_override TINYINT NOT NULL DEFAULT 0,
                    review_status VARCHAR(32),
                    review_note TEXT,
                    reviewed_by VARCHAR(128),
                    reviewed_at DATETIME,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    KEY idx_case_timeline (case_id, node_date),
                    KEY idx_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_lifecycle_condition (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    clause_id BIGINT,
                    condition_type VARCHAR(64) NOT NULL DEFAULT 'CONTRACT_END',
                    end_mode VARCHAR(32) NOT NULL DEFAULT 'CONDITIONAL',
                    logic_operator VARCHAR(16) NOT NULL DEFAULT 'SINGLE',
                    summary TEXT NOT NULL,
                    conditions_json LONGTEXT NOT NULL,
                    citation_json LONGTEXT,
                    confidence DECIMAL(5,4),
                    source VARCHAR(64) NOT NULL DEFAULT 'RULE_CANDIDATE',
                    status VARCHAR(64) NOT NULL DEFAULT 'NEEDS_REVIEW',
                    manual_override TINYINT NOT NULL DEFAULT 0,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    KEY idx_case_lifecycle (case_id, condition_type, create_time),
                    KEY idx_document_lifecycle (document_id, clause_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_analysis_workflow (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    intake_id BIGINT,
                    document_id BIGINT,
                    document_version INT,
                    evidence_snapshot_hash VARCHAR(128),
                    confirmed_version INT NOT NULL DEFAULT 0,
                    status VARCHAR(32) NOT NULL DEFAULT 'PARSING',
                    current_stage VARCHAR(64) NOT NULL DEFAULT 'DOCUMENT_PARSE',
                    review_run_id BIGINT,
                    last_error TEXT,
                    confirmed_at DATETIME,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    KEY idx_analysis_workflow_case (case_id, id),
                    KEY idx_analysis_workflow_status (status, update_time),
                    KEY idx_analysis_workflow_document (document_id, document_version),
                    KEY idx_analysis_workflow_run (review_run_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        // Workflow status is read and written by Java, while the Python
        // runtime owns the versioned extraction fact tables themselves.
        addColumnIfMissing("contract_analysis_workflow", "extraction_snapshot_id", "BIGINT");
        addColumnIfMissing("contract_analysis_workflow", "extraction_run_id", "BIGINT");
        addColumnIfMissing("contract_analysis_workflow", "extraction_status", "VARCHAR(32)");
        addColumnIfMissing("contract_analysis_workflow", "timeline_run_id", "BIGINT");
        addColumnIfMissing("contract_analysis_workflow", "timeline_status", "VARCHAR(32)");
        addContractExtractionProfileColumnsIfPresent();
        addContractFactReviewColumnsIfPresent();
        addColumnIfMissing("contract_timeline_node", "review_status", "VARCHAR(32)");
        addColumnIfMissing("contract_timeline_node", "review_note", "TEXT");
        addColumnIfMissing("contract_timeline_node", "reviewed_by", "VARCHAR(128)");
        addColumnIfMissing("contract_timeline_node", "reviewed_at", "DATETIME");
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_fact_review (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    fact_key VARCHAR(128) NOT NULL,
                    fact_identity VARCHAR(256) NOT NULL,
                    fact_label VARCHAR(256),
                    value_hash VARCHAR(128),
                    review_status VARCHAR(32) NOT NULL DEFAULT 'CONFIRMED',
                    review_note TEXT,
                    reviewed_by VARCHAR(128),
                    reviewed_at DATETIME,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_case_fact_identity (case_id, fact_identity),
                    KEY idx_case_fact_key (case_id, fact_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        addAgentRunRuntimeColumnsIfMissing();
        addColumnIfMissing("agent_report", "report_type",
                "VARCHAR(40) NOT NULL DEFAULT 'HEALTH_REPORT'");
        addColumnIfMissing("agent_report", "scoring_version", "VARCHAR(30)");
        addColumnIfMissing("agent_report", "evidence_hash", "VARCHAR(64)");
        addColumnIfMissing("agent_report", "analysis_mode", "VARCHAR(80)");
        addColumnIfMissing("agent_report", "scoring_rationale_json", "LONGTEXT");
        addColumnIfMissing("agent_report", "content_json", "LONGTEXT");
        addColumnIfMissing("agent_report", "subject_type", "VARCHAR(32) DEFAULT 'PROJECT'");
        addColumnIfMissing("agent_report", "subject_id", "BIGINT");
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_fulfillment_check (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    timeline_node_id BIGINT NOT NULL,
                    run_id BIGINT,
                    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                    conclusion VARCHAR(64),
                    risk_level VARCHAR(16),
                    confidence_level VARCHAR(16),
                    summary TEXT,
                    requirement_json LONGTEXT,
                    evidence_snapshot_json LONGTEXT,
                    missing_evidence_json LONGTEXT,
                    explicit_consequence TEXT,
                    ai_risk TEXT,
                    suggested_actions_json LONGTEXT,
                    manual_result VARCHAR(32),
                    manual_note TEXT,
                    confirmed_by VARCHAR(128),
                    confirmed_at DATETIME,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    KEY idx_case_node (case_id, timeline_node_id, create_time),
                    KEY idx_run (run_id),
                    KEY idx_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        addColumnIfMissing("contract_document", "deleted", "TINYINT NOT NULL DEFAULT 0");
        addColumnIfMissing("contract_document", "preprocess_status",
                "VARCHAR(16) DEFAULT 'PENDING' COMMENT 'PENDING|READY|FAILED|SKIPPED'");
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_timeline_evidence_link (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    timeline_node_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    check_id BIGINT,
                    link_source VARCHAR(32) NOT NULL DEFAULT 'AGENT',
                    relation_type VARCHAR(64) NOT NULL DEFAULT 'FULFILLMENT_EVIDENCE',
                    evidence_version INT,
                    evidence_hash VARCHAR(128),
                    snippet TEXT,
                    deleted TINYINT NOT NULL DEFAULT 0,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_node_document_check (timeline_node_id, document_id, check_id),
                    KEY idx_case_node (case_id, timeline_node_id, deleted),
                    KEY idx_document_node (document_id, timeline_node_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        // ── Graph Runtime infrastructure tables ────────────────────────
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS agent_graph_checkpoint (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    run_id BIGINT NOT NULL,
                    graph_name VARCHAR(64) NOT NULL DEFAULT '',
                    graph_version VARCHAR(32) NOT NULL DEFAULT 'v1',
                    thread_id VARCHAR(128) NOT NULL,
                    checkpoint_id VARCHAR(128) NOT NULL,
                    state_revision INT NOT NULL DEFAULT 0,
                    node_name VARCHAR(128) NOT NULL DEFAULT '',
                    state_json LONGTEXT NOT NULL,
                    state_hash CHAR(64) NOT NULL DEFAULT '',
                    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_thread (thread_id, status),
                    INDEX idx_run (run_id),
                    UNIQUE KEY uk_checkpoint (thread_id, checkpoint_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS agent_node_execution (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    run_id BIGINT NOT NULL,
                    node_name VARCHAR(128) NOT NULL,
                    node_type VARCHAR(32) NOT NULL DEFAULT 'COMPUTE',
                    sequence_no INT NOT NULL DEFAULT 0,
                    attempt INT NOT NULL DEFAULT 1,
                    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                    input_hash CHAR(64) DEFAULT '',
                    output_hash CHAR(64) DEFAULT '',
                    started_at DATETIME NULL,
                    finished_at DATETIME NULL,
                    latency_ms BIGINT DEFAULT 0,
                    llm_model VARCHAR(64) DEFAULT '',
                    prompt_version VARCHAR(32) DEFAULT '',
                    token_input INT DEFAULT 0,
                    token_output INT DEFAULT 0,
                    input_summary LONGTEXT,
                    output_summary LONGTEXT,
                    error_code VARCHAR(32) DEFAULT '',
                    error_message TEXT,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_run_node (run_id, node_name, attempt),
                    INDEX idx_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        addColumnIfMissing("agent_node_execution", "node_type", "VARCHAR(32) NOT NULL DEFAULT 'COMPUTE'");
        addColumnIfMissing("agent_node_execution", "sequence_no", "INT NOT NULL DEFAULT 0");
        addColumnIfMissing("agent_node_execution", "attempt", "INT NOT NULL DEFAULT 1");
        addColumnIfMissing("agent_node_execution", "input_hash", "CHAR(64) DEFAULT ''");
        addColumnIfMissing("agent_node_execution", "output_hash", "CHAR(64) DEFAULT ''");
        addColumnIfMissing("agent_node_execution", "llm_model", "VARCHAR(128) DEFAULT ''");
        addColumnIfMissing("agent_node_execution", "prompt_version", "VARCHAR(64) DEFAULT ''");
        addColumnIfMissing("agent_node_execution", "token_input", "INT DEFAULT 0");
        addColumnIfMissing("agent_node_execution", "token_output", "INT DEFAULT 0");
        addColumnIfMissing("agent_node_execution", "input_summary", "LONGTEXT");
        addColumnIfMissing("agent_node_execution", "output_summary", "LONGTEXT");
        addColumnIfMissing("agent_node_execution", "error_code", "VARCHAR(32) DEFAULT ''");
        addColumnIfMissing("agent_node_execution", "error_message", "TEXT");
        // ── Evaluation center tables ─────────────────────────────────
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS agent_eval_dataset (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    version VARCHAR(32) NOT NULL DEFAULT 'v1',
                    description VARCHAR(1000) DEFAULT '',
                    contract_type VARCHAR(64) DEFAULT 'SERVICE_PROCUREMENT',
                    task_purpose VARCHAR(64) DEFAULT '',
                    case_count INT DEFAULT 0,
                    status VARCHAR(32) DEFAULT 'DRAFT',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        // PRD Phase 8 task 1: evaluation sets are distinguished by task
        // purpose (要素提取 / 履约日程 / 风险审查 / 履约核验 / 综合).
        addColumnIfMissing("agent_eval_dataset", "task_purpose", "VARCHAR(64) DEFAULT ''");
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS agent_eval_case (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    dataset_id BIGINT NOT NULL,
                    case_key VARCHAR(128) NOT NULL,
                    title VARCHAR(512) DEFAULT '',
                    contract_type VARCHAR(64) DEFAULT 'SERVICE_PROCUREMENT',
                    contract_text LONGTEXT,
                    expected_findings_json LONGTEXT,
                    should_not_find_json LONGTEXT,
                    expected_citation_count INT DEFAULT 0,
                    status VARCHAR(32) DEFAULT 'ACTIVE',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_dataset (dataset_id),
                    UNIQUE KEY uk_dataset_case (dataset_id, case_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS agent_eval_run (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    dataset_id BIGINT NOT NULL,
                    runtime_engine VARCHAR(32) NOT NULL DEFAULT 'legacy',
                    graph_name VARCHAR(64) DEFAULT '',
                    graph_version VARCHAR(32) DEFAULT '',
                    llm_model VARCHAR(64) DEFAULT '',
                    prompt_version VARCHAR(32) DEFAULT '',
                    status VARCHAR(32) DEFAULT 'RUNNING',
                    high_risk_recall DOUBLE DEFAULT 0,
                    dual_citation_rate DOUBLE DEFAULT 0,
                    false_positive_rate DOUBLE DEFAULT 0,
                    schema_valid_rate DOUBLE DEFAULT 0,
                    case_count INT DEFAULT 0,
                    passed_count INT DEFAULT 0,
                    summary_json LONGTEXT,
                    started_at DATETIME NULL,
                    finished_at DATETIME NULL,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_dataset (dataset_id),
                    INDEX idx_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS agent_eval_result (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    run_id BIGINT NOT NULL,
                    case_id BIGINT NOT NULL,
                    success TINYINT DEFAULT 0,
                    high_recall DOUBLE DEFAULT 0,
                    dual_citation_rate DOUBLE DEFAULT 0,
                    false_positives INT DEFAULT 0,
                    analysis_mode VARCHAR(32) DEFAULT 'FULL',
                    risk_score DOUBLE DEFAULT 0,
                    finding_count INT DEFAULT 0,
                    error_message TEXT,
                    result_json LONGTEXT,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_run (run_id),
                    UNIQUE KEY uk_run_case (run_id, case_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        // ── Add features_json column (safe ALTER, may already exist) ────
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_run
                    ADD COLUMN features_json LONGTEXT
                    """);
        } catch (Exception ignored) {
            // Column may already exist — safe to ignore
        }
        // ── Backfill metric columns for pre-existing tables ──────────
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_run
                    ADD COLUMN false_positive_rate DOUBLE DEFAULT 0
                    """);
        } catch (Exception ignored) { }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_run
                    ADD COLUMN schema_valid_rate DOUBLE DEFAULT 0
                    """);
        } catch (Exception ignored) { }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_run
                    ADD COLUMN passed_count INT DEFAULT 0
                    """);
        } catch (Exception ignored) { }
        addColumnIfMissing("agent_eval_run", "current_case_index", "INT DEFAULT 0");
        addColumnIfMissing("agent_eval_run", "current_case_key", "VARCHAR(128) DEFAULT ''");
        addColumnIfMissing("agent_eval_run", "current_step", "VARCHAR(256) DEFAULT ''");
        addColumnIfMissing("agent_eval_run", "queue_position", "INT DEFAULT 0");
        addColumnIfMissing("agent_eval_run", "environment_status", "VARCHAR(32) DEFAULT ''");
        addColumnIfMissing("agent_eval_run", "environment_snapshot_json", "LONGTEXT");
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_result
                    ADD COLUMN false_positives INT DEFAULT 0
                    """);
        } catch (Exception ignored) { }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_result
                    ADD COLUMN dual_citation_rate DOUBLE DEFAULT 0
                    """);
        } catch (Exception ignored) { }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_result
                    ADD COLUMN schema_valid_rate DOUBLE DEFAULT 0
                    """);
        } catch (Exception ignored) { }
        // ── Eval case enrichment columns (safe ALTER) ──────────────────
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_case
                    ADD COLUMN scenario VARCHAR(64) DEFAULT ''
                    """);
        } catch (Exception ignored) { }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_case
                    ADD COLUMN industry VARCHAR(64) DEFAULT ''
                    """);
        } catch (Exception ignored) { }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_case
                    ADD COLUMN difficulty VARCHAR(32) DEFAULT ''
                    """);
        } catch (Exception ignored) { }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_case
                    ADD COLUMN noise_level VARCHAR(32) DEFAULT ''
                    """);
        } catch (Exception ignored) { }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_case
                    ADD COLUMN must_have_contract_citation TINYINT(1) DEFAULT 0
                    """);
        } catch (Exception ignored) { }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE agent_eval_case
                    ADD COLUMN must_have_policy_citation TINYINT(1) DEFAULT 0
                    """);
        } catch (Exception ignored) { }
        // Fulfillment evaluation has inputs that are deliberately separate
        // from the contract: target node selection, uploaded proof, expected
        // AI judgements, and the controlled human decision.
        addColumnIfMissing("agent_eval_case", "fulfillment_evidence_json", "LONGTEXT");
        addColumnIfMissing("agent_eval_case", "target_timeline_selector_json", "LONGTEXT");
        addColumnIfMissing("agent_eval_case", "expected_judgements_json", "LONGTEXT");
        addColumnIfMissing("agent_eval_case", "expected_manual_result", "VARCHAR(32) DEFAULT ''");
        jdbcTemplate.update("""
                INSERT IGNORE INTO system_config (config_key, config_value)
                VALUES ('AGENT_RUNTIME', 'java')
                """);
        // ── Graph Runtime routing config seeds ─────────────────────────
        jdbcTemplate.update("""
                INSERT IGNORE INTO system_config (config_key, config_value)
                VALUES ('agent.runtime.default', 'legacy')
                """);
        jdbcTemplate.update("""
                INSERT IGNORE INTO system_config (config_key, config_value)
                VALUES ('agent.runtime.CONTRACT_REVIEW', 'legacy')
                """);
        jdbcTemplate.update("""
                INSERT IGNORE INTO system_config (config_key, config_value)
                VALUES ('agent.runtime.FULFILLMENT_CHECK', 'legacy')
                """);
        jdbcTemplate.update("""
                INSERT INTO agent_project
                (name, project_key, description, repository_type, repository_url, default_branch,
                 business_scope, release_target, current_milestone, team_size, tech_stack,
                health_status, health_score, deleted)
                SELECT 'AtlasMind Agent Workbench', 'ATLASMIND',
                       '面向企业研发团队的智能交付 Agent 工作台，用于项目健康分析、风险发现和交付规划。',
                       'GITHUB', 'https://github.com/DayDayUpStudyHard/AtlasMind-Agent-Workbench',
                       'master', '企业研发团队内部项目治理与交付协同', '2026 Q3',
                       'MVP：项目健康分析与交付计划', 1,
                       'Spring Boot / Vue 3 / FastAPI / MySQL / Redis / Elasticsearch',
                       'UNKNOWN', 0, 0
                WHERE NOT EXISTS (SELECT 1 FROM agent_project WHERE project_key='ATLASMIND')
                """);
        jdbcTemplate.update("""
                UPDATE agent_project
                SET description='面向企业研发团队的智能交付 Agent 工作台，用于项目健康分析、风险发现和交付规划。',
                    business_scope='企业研发团队内部项目治理与交付协同',
                    current_milestone='MVP：项目健康分析与交付计划'
                WHERE project_key='ATLASMIND'
                """);
        jdbcTemplate.update("""
                INSERT INTO project_source (project_id, source_type, source_url, default_branch, status)
                SELECT id, repository_type, repository_url, default_branch, 'PENDING'
                FROM agent_project p
                WHERE p.project_key='ATLASMIND'
                  AND p.repository_url IS NOT NULL
                  AND p.repository_url <> ''
                  AND NOT EXISTS (
                      SELECT 1 FROM project_source s
                      WHERE s.project_id=p.id AND s.source_url=p.repository_url
                  )
                """);

        // ── Auth & Permission DDL ─────────────────────────────────────
        // t_user extension
        addColumnIfMissing("t_user", "role",
                "VARCHAR(16) NOT NULL DEFAULT 'USER' COMMENT 'ADMIN|USER'");
        addColumnIfMissing("t_user", "department_id", "BIGINT DEFAULT NULL");
        addColumnIfMissing("t_user", "status",
                "VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE|DISABLED'");
        // department table
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS department (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    code VARCHAR(60) NOT NULL,
                    is_default TINYINT NOT NULL DEFAULT 0 COMMENT '默认部门标记，禁止删除',
                    description VARCHAR(500) DEFAULT '',
                    deleted TINYINT NOT NULL DEFAULT 0,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_code (code),
                    INDEX idx_deleted (deleted)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        // refresh token table
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS user_refresh_token (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    token_hash CHAR(64) NOT NULL COMMENT 'SHA-256(token)',
                    family VARCHAR(64) NOT NULL COMMENT 'token family 标识，rotation 时保持',
                    expires_at DATETIME NOT NULL,
                    revoked TINYINT NOT NULL DEFAULT 0,
                    revoked_reason VARCHAR(64) DEFAULT NULL COMMENT 'LOGOUT|ROTATION|REUSE_DETECTED',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_family (user_id, family),
                    INDEX idx_expires (expires_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        addColumnIfMissing("user_refresh_token", "id",
                "BIGINT AUTO_INCREMENT PRIMARY KEY");
        // token_hash unique index (may fail if already exists via PK, safe to try)
        try { jdbcTemplate.execute("""
                ALTER TABLE user_refresh_token ADD UNIQUE INDEX uk_token_hash (token_hash)
                """); } catch (Exception ignored) {}
        // user_quota table
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS user_quota (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    total_quota INT NOT NULL DEFAULT 0,
                    used_count INT NOT NULL DEFAULT 0,
                    reserved_count INT NOT NULL DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_user (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        // quota_transaction table
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS quota_transaction (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount INT NOT NULL COMMENT '变动量',
                    type VARCHAR(32) NOT NULL COMMENT 'ALLOCATE|RESERVE|CONFIRM|REFUND|ADMIN_ADJUST',
                    balance_after INT NOT NULL COMMENT '变动后 available = total - used - reserved',
                    operator_id BIGINT COMMENT '管理员操作时记录',
                    run_id BIGINT COMMENT '关联 agent_run',
                    remark VARCHAR(500) DEFAULT '',
                    idempotency_key VARCHAR(128) DEFAULT NULL COMMENT '幂等键（run_id + type）',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_time (user_id, create_time),
                    INDEX idx_run (run_id),
                    UNIQUE KEY uk_idempotency (idempotency_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS private_upload (
                    path VARCHAR(512) PRIMARY KEY,
                    owner_id BIGINT NOT NULL,
                    original_name VARCHAR(512) DEFAULT '',
                    content_type VARCHAR(128) DEFAULT 'application/octet-stream',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_private_upload_owner (owner_id, create_time)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        // contract_case extension
        addColumnIfMissing("contract_case", "visibility",
                "VARCHAR(16) NOT NULL DEFAULT 'LEGACY_REVIEW' COMMENT 'LEGACY_REVIEW|DEPARTMENT|SPECIFIED|ALL'");
        addColumnIfMissing("contract_case", "creator_id",
                "BIGINT DEFAULT NULL COMMENT '上传人'");
        addColumnIfMissing("contract_case", "maintainer_id",
                "BIGINT DEFAULT NULL COMMENT '维护人'");
        addColumnIfMissing("contract_case", "department_id",
                "BIGINT DEFAULT NULL COMMENT '创建时的部门快照（不可变）'");
        // Internal evaluation fixtures are never part of the normal contract workspace.
        addColumnIfMissing("contract_case", "is_evaluation",
                "TINYINT NOT NULL DEFAULT 0 COMMENT 'Internal evaluation fixture'");
        jdbcTemplate.update("""
                UPDATE contract_case
                SET is_evaluation=1
                WHERE case_key LIKE 'EVAL-%' AND COALESCE(is_evaluation,0)=0
                """);
        // contract_department_visibility
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_department_visibility (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    contract_id BIGINT NOT NULL,
                    department_id BIGINT NOT NULL,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_contract_dept (contract_id, department_id),
                    INDEX idx_dept_contract (department_id, contract_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        // contract_document extension — 文件物理状态与安全扫描
        addColumnIfMissing("contract_document", "storage_status",
                "VARCHAR(16) NOT NULL DEFAULT 'AVAILABLE' COMMENT 'AVAILABLE|QUARANTINED|DELETED'");
        addColumnIfMissing("contract_document", "storage_key",
                "VARCHAR(512) DEFAULT NULL COMMENT '内部存储 key，替代 file_path 作为安全边界'");
        addColumnIfMissing("contract_document", "content_type",
                "VARCHAR(128) DEFAULT NULL COMMENT 'MIME 类型'");
        addColumnIfMissing("contract_document", "scan_status",
                "VARCHAR(16) NOT NULL DEFAULT 'UNSCANNED' COMMENT 'UNSCANNED|CLEAN|INFECTED'");
        // file_access_log — 文件下载审计
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS file_access_log (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    access_type VARCHAR(16) NOT NULL COMMENT 'DOWNLOAD|PREVIEW|THUMBNAIL',
                    ip VARCHAR(45),
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_document_time (document_id, create_time),
                    INDEX idx_user_time (user_id, create_time),
                    INDEX idx_case_time (case_id, create_time)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        // contract_member — 合同协作成员
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS contract_member (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    role VARCHAR(16) NOT NULL DEFAULT 'VIEWER' COMMENT 'OWNER|EDITOR|REVIEWER|VIEWER',
                    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE|INVITED|REMOVED',
                    invited_by BIGINT COMMENT '邀请人 user_id',
                    joined_at DATETIME COMMENT '接受邀请时间',
                    removed_at DATETIME COMMENT '移除时间',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_case_user (case_id, user_id),
                    INDEX idx_user (user_id),
                    INDEX idx_case_role (case_id, role)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        addColumnIfMissing("kb_qa_session", "case_id",
                "BIGINT DEFAULT NULL COMMENT '鍏宠仈鐨勫悎鍚屾浠?case_id'");
        // t_operation_log extension
        addColumnIfMissing("t_operation_log", "operator_id", "BIGINT DEFAULT NULL");
        addColumnIfMissing("t_operation_log", "target_type", "VARCHAR(64) DEFAULT NULL");
        addColumnIfMissing("t_operation_log", "target_id", "BIGINT DEFAULT NULL");
        addColumnIfMissing("t_operation_log", "target_label", "VARCHAR(256) DEFAULT NULL");
        addColumnIfMissing("t_operation_log", "old_value_json", "LONGTEXT");
        addColumnIfMissing("t_operation_log", "new_value_json", "LONGTEXT");
    }

    private void addColumnIfMissing(String tableName, String columnName, String definition) {
        Integer count = jdbcTemplate.queryForObject("""
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND COLUMN_NAME=?
                """, Integer.class, tableName, columnName);
        if (count != null && count > 0) return;
        jdbcTemplate.execute("ALTER TABLE `" + tableName + "` ADD COLUMN `"
                + columnName + "` " + definition);
    }

    void addAgentRunRuntimeColumnsIfMissing() {
        addColumnIfMissing("agent_run", "subject_type", "VARCHAR(32) DEFAULT 'PROJECT'");
        addColumnIfMissing("agent_run", "subject_id", "BIGINT");
        addColumnIfMissing("agent_run", "input_json", "LONGTEXT");
        addColumnIfMissing("agent_run", "limited_diagnostics", "JSON");
        addColumnIfMissing("agent_run", "workflow_id", "BIGINT");
        addColumnIfMissing("agent_run", "workflow_stage", "VARCHAR(64)");
        addColumnIfMissing("agent_run", "evidence_snapshot_hash", "VARCHAR(128)");
        addColumnIfMissing("agent_run", "runtime_engine", "VARCHAR(32)");
        addColumnIfMissing("agent_run", "graph_name", "VARCHAR(128)");
        addColumnIfMissing("agent_run", "graph_version", "VARCHAR(64)");
        addColumnIfMissing("agent_run", "model", "VARCHAR(128)");
        addColumnIfMissing("agent_run", "prompt_version", "VARCHAR(64)");
        addColumnIfMissing("agent_run", "retrieval_version", "VARCHAR(64)");
        addColumnIfMissing("agent_run", "rerank_version", "VARCHAR(64)");
        addColumnIfMissing("agent_run", "scorer_version", "VARCHAR(64)");
        addColumnIfMissing("agent_run", "initiated_by",
                "BIGINT DEFAULT NULL COMMENT '发起人 user_id（额度归属依据）'");
        addColumnIfMissing("agent_run", "document_snapshot_json",
                "LONGTEXT COMMENT '启动时的文件快照 [{documentId, version, contentHash, storageKey}]'");
        addColumnIfMissing("agent_run", "last_heartbeat_at", "DATETIME");
    }

    private void addContractExtractionProfileColumnsIfPresent() {
        Integer tableCount = jdbcTemplate.queryForObject("""
                SELECT COUNT(*)
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='contract_extraction_snapshot'
                """, Integer.class);
        if (tableCount == null || tableCount == 0) return;
        addColumnIfMissing("contract_extraction_snapshot", "profile_schema_version", "VARCHAR(64)");
        addColumnIfMissing("contract_extraction_snapshot", "profile_json", "LONGTEXT");
        addColumnIfMissing("contract_extraction_snapshot", "profile_hash", "VARCHAR(128)");
        addColumnIfMissing("contract_extraction_snapshot", "profile_status", "VARCHAR(32)");
    }

    private void addContractFactReviewColumnsIfPresent() {
        Integer tableCount = jdbcTemplate.queryForObject("""
                SELECT COUNT(*)
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='contract_extracted_element'
                """, Integer.class);
        if (tableCount == null || tableCount == 0) return;
        addColumnIfMissing("contract_extracted_element", "review_status", "VARCHAR(32)");
        addColumnIfMissing("contract_extracted_element", "review_note", "TEXT");
        addColumnIfMissing("contract_extracted_element", "reviewed_by", "VARCHAR(128)");
        addColumnIfMissing("contract_extracted_element", "reviewed_at", "DATETIME");
    }
}
