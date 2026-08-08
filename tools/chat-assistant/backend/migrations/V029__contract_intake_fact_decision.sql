-- V029: Auditable promotion of intake candidates into canonical case facts.

CREATE TABLE IF NOT EXISTS contract_intake_fact_decision (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    intake_id BIGINT NOT NULL,
    document_id BIGINT NULL,
    field_key VARCHAR(64) NOT NULL,
    proposed_value_json LONGTEXT NULL,
    confirmed_value_json LONGTEXT NULL,
    decision_type VARCHAR(24) NOT NULL DEFAULT 'ACCEPTED',
    candidate_source VARCHAR(32) NULL,
    candidate_confidence DECIMAL(5,4) NULL,
    citations_json LONGTEXT NULL,
    validation_json LONGTEXT NULL,
    content_hash VARCHAR(128) NULL,
    parser_version VARCHAR(64) NULL,
    schema_version VARCHAR(64) NULL,
    prompt_version VARCHAR(64) NULL,
    llm_model VARCHAR(128) NULL,
    decided_by BIGINT NULL,
    decided_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_intake_fact_decision (intake_id, field_key),
    KEY idx_intake_fact_decision_case (case_id, decided_at),
    KEY idx_intake_fact_decision_document (document_id, field_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
