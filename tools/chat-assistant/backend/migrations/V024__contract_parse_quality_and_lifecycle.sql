-- V024: Preserve PDF parse diagnostics and event-driven contract end conditions.

ALTER TABLE contract_document
    ADD COLUMN IF NOT EXISTS parse_provider VARCHAR(128) NULL AFTER parse_error,
    ADD COLUMN IF NOT EXISTS parse_quality VARCHAR(32) NULL AFTER parse_provider,
    ADD COLUMN IF NOT EXISTS parse_diagnostics_json LONGTEXT NULL AFTER parse_quality;

CREATE TABLE IF NOT EXISTS contract_lifecycle_condition (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    document_id BIGINT NOT NULL,
    clause_id BIGINT NULL,
    condition_type VARCHAR(64) NOT NULL DEFAULT 'CONTRACT_END',
    end_mode VARCHAR(32) NOT NULL DEFAULT 'CONDITIONAL',
    logic_operator VARCHAR(16) NOT NULL DEFAULT 'SINGLE',
    summary TEXT NOT NULL,
    conditions_json LONGTEXT NOT NULL,
    citation_json LONGTEXT NULL,
    confidence DECIMAL(5,4) NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'RULE_CANDIDATE',
    status VARCHAR(64) NOT NULL DEFAULT 'NEEDS_REVIEW',
    manual_override TINYINT NOT NULL DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_case_lifecycle (case_id, condition_type, create_time),
    KEY idx_document_lifecycle (document_id, clause_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
