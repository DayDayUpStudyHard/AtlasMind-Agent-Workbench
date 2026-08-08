-- V026: Versioned contract extraction facts and graph observability.

CREATE TABLE IF NOT EXISTS contract_element_definition (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    element_key VARCHAR(128) NOT NULL,
    element_name VARCHAR(256) NOT NULL,
    category VARCHAR(64) NOT NULL,
    value_type VARCHAR(32) NOT NULL DEFAULT 'TEXT',
    applies_to VARCHAR(128) NOT NULL DEFAULT 'ALL',
    required_mode VARCHAR(32) NOT NULL DEFAULT 'OPTIONAL',
    validation_rule_json LONGTEXT NULL,
    display_order INT NOT NULL DEFAULT 0,
    version INT NOT NULL DEFAULT 1,
    enabled TINYINT NOT NULL DEFAULT 1,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_element_definition (element_key, version),
    KEY idx_element_definition_category (category, enabled, display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS contract_extraction_snapshot (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    document_id BIGINT NOT NULL,
    document_version INT NULL,
    content_hash VARCHAR(128) NOT NULL,
    parser_version VARCHAR(64) NULL,
    schema_version VARCHAR(64) NOT NULL,
    prompt_version VARCHAR(64) NULL,
    llm_model VARCHAR(128) NULL,
    retrieval_version VARCHAR(64) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'RUNNING',
    snapshot_hash VARCHAR(128) NULL,
    source_run_id BIGINT NULL,
    confirmed_by VARCHAR(128) NULL,
    confirmed_at DATETIME NULL,
    error_message TEXT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_extraction_snapshot_input (case_id, document_id, content_hash, schema_version, prompt_version, retrieval_version),
    KEY idx_extraction_snapshot_case (case_id, id),
    KEY idx_extraction_snapshot_document (document_id, document_version),
    KEY idx_extraction_snapshot_run (source_run_id),
    KEY idx_extraction_snapshot_status (status, update_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS contract_extracted_element (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    snapshot_id BIGINT NOT NULL,
    element_key VARCHAR(128) NOT NULL,
    category VARCHAR(64) NOT NULL,
    value_type VARCHAR(32) NOT NULL DEFAULT 'TEXT',
    raw_value TEXT NULL,
    normalized_value_json LONGTEXT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'EXTRACTED',
    confidence DECIMAL(5,4) NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'LLM',
    applicable TINYINT NOT NULL DEFAULT 1,
    occurrence_no INT NOT NULL DEFAULT 1,
    parent_element_id BIGINT NULL,
    manual_override TINYINT NOT NULL DEFAULT 0,
    validation_json LONGTEXT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_extracted_element_snapshot (snapshot_id, category, element_key),
    KEY idx_extracted_element_key (element_key, status),
    KEY idx_extracted_element_parent (parent_element_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS contract_element_candidate (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    element_id BIGINT NOT NULL,
    raw_value TEXT NULL,
    normalized_value_json LONGTEXT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'LLM',
    confidence DECIMAL(5,4) NULL,
    selected TINYINT NOT NULL DEFAULT 0,
    reason VARCHAR(500) NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_element_candidate_element (element_id, selected, confidence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS contract_element_evidence_link (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    element_id BIGINT NOT NULL,
    document_id BIGINT NULL,
    clause_id BIGINT NULL,
    chunk_id BIGINT NULL,
    page_number INT NULL,
    paragraph_index INT NULL,
    quote TEXT NOT NULL,
    start_offset INT NULL,
    end_offset INT NULL,
    bbox_json LONGTEXT NULL,
    retrieval_method VARCHAR(64) NULL,
    score DECIMAL(12,6) NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_element_evidence_element (element_id, id),
    KEY idx_element_evidence_clause (clause_id, document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_node_execution (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL,
    node_name VARCHAR(128) NOT NULL,
    node_type VARCHAR(32) NOT NULL DEFAULT 'COMPUTE',
    sequence_no INT NOT NULL,
    attempt INT NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL DEFAULT 'DONE',
    input_hash CHAR(64) DEFAULT '',
    output_hash CHAR(64) DEFAULT '',
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    latency_ms BIGINT NULL,
    llm_model VARCHAR(128) NULL,
    prompt_version VARCHAR(64) NULL,
    token_input INT DEFAULT 0,
    token_output INT DEFAULT 0,
    input_summary LONGTEXT NULL,
    output_summary LONGTEXT NULL,
    error_code VARCHAR(32) DEFAULT '',
    error_message TEXT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_node_execution_sequence (run_id, sequence_no),
    KEY idx_node_execution_run (run_id, node_name, sequence_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE agent_node_execution
    ADD COLUMN IF NOT EXISTS node_type VARCHAR(32) NOT NULL DEFAULT 'COMPUTE',
    ADD COLUMN IF NOT EXISTS sequence_no INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS attempt INT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS input_hash CHAR(64) DEFAULT '',
    ADD COLUMN IF NOT EXISTS output_hash CHAR(64) DEFAULT '',
    ADD COLUMN IF NOT EXISTS llm_model VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS token_input INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS token_output INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS input_summary LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS output_summary LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS error_code VARCHAR(32) DEFAULT '',
    ADD COLUMN IF NOT EXISTS error_message TEXT NULL;

ALTER TABLE contract_timeline_node
    ADD COLUMN IF NOT EXISTS extraction_snapshot_id BIGINT NULL,
    ADD COLUMN IF NOT EXISTS source_element_id BIGINT NULL,
    ADD COLUMN IF NOT EXISTS base_date_candidates_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS base_date_status VARCHAR(32) NULL;

ALTER TABLE contract_obligation
    ADD COLUMN IF NOT EXISTS source_element_id BIGINT NULL,
    ADD COLUMN IF NOT EXISTS required_materials_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS acceptance_criteria_json LONGTEXT NULL;

ALTER TABLE contract_analysis_workflow
    ADD COLUMN IF NOT EXISTS extraction_snapshot_id BIGINT NULL,
    ADD COLUMN IF NOT EXISTS extraction_run_id BIGINT NULL,
    ADD COLUMN IF NOT EXISTS extraction_status VARCHAR(32) NULL;

ALTER TABLE agent_run
    ADD COLUMN IF NOT EXISTS runtime_engine VARCHAR(32) NULL,
    ADD COLUMN IF NOT EXISTS graph_name VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS graph_version VARCHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS model VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(64) NULL;

INSERT IGNORE INTO contract_element_definition
    (element_key, element_name, category, value_type, applies_to, required_mode, display_order, version)
VALUES
    ('contract_title', '合同标题', 'IDENTITY', 'TEXT', 'ALL', 'REQUIRED', 10, 1),
    ('contract_type', '合同类型', 'IDENTITY', 'ENUM', 'ALL', 'REQUIRED', 20, 1),
    ('party_a', '甲方主体', 'PARTIES', 'PARTY', 'ALL', 'REQUIRED', 30, 1),
    ('party_b', '乙方主体', 'PARTIES', 'PARTY', 'ALL', 'REQUIRED', 40, 1),
    ('our_side', '我方角色', 'PARTIES', 'ENUM', 'ALL', 'REQUIRED', 50, 1),
    ('contract_amount', '合同金额', 'FINANCIAL', 'MONEY', 'ALL', 'OPTIONAL', 60, 1),
    ('payment_terms', '付款与开票条件', 'FINANCIAL', 'STRUCTURED', 'ALL', 'OPTIONAL', 70, 1),
    ('effective_date', '生效日期', 'DATES', 'DATE', 'ALL', 'OPTIONAL', 80, 1),
    ('expiry_date', '固定到期日期', 'DATES', 'DATE', 'ALL', 'OPTIONAL', 90, 1),
    ('termination_conditions', '终止与结束条件', 'DATES', 'STRUCTURED', 'ALL', 'OPTIONAL', 100, 1),
    ('delivery_obligations', '交付与服务义务', 'OBLIGATIONS', 'LIST', 'ALL', 'OPTIONAL', 110, 1),
    ('acceptance_criteria', '验收标准', 'OBLIGATIONS', 'LIST', 'ALL', 'OPTIONAL', 120, 1),
    ('required_materials', '应提交材料', 'OBLIGATIONS', 'LIST', 'ALL', 'OPTIONAL', 130, 1),
    ('liability_terms', '违约与责任', 'RISK_TERMS', 'STRUCTURED', 'ALL', 'OPTIONAL', 140, 1),
    ('ip_ownership', '知识产权归属与许可', 'RISK_TERMS', 'STRUCTURED', 'ALL', 'OPTIONAL', 150, 1),
    ('confidentiality_terms', '保密义务', 'RISK_TERMS', 'STRUCTURED', 'ALL', 'OPTIONAL', 160, 1),
    ('data_protection_terms', '数据与个人信息处理', 'RISK_TERMS', 'STRUCTURED', 'ALL', 'OPTIONAL', 170, 1),
    ('compliance_terms', '合规与监管要求', 'RISK_TERMS', 'STRUCTURED', 'ALL', 'OPTIONAL', 180, 1),
    ('dispute_resolution', '争议解决', 'RISK_TERMS', 'STRUCTURED', 'ALL', 'OPTIONAL', 190, 1),
    ('notice_terms', '通知与送达', 'RISK_TERMS', 'STRUCTURED', 'ALL', 'OPTIONAL', 200, 1);
