-- V020: Contract Agent knowledge usage scope.

ALTER TABLE kb_document
    ADD COLUMN IF NOT EXISTS contract_usage_scope VARCHAR(32) NOT NULL DEFAULT 'DISABLED',
    ADD COLUMN IF NOT EXISTS contract_usage_summary VARCHAR(256) NULL,
    ADD COLUMN IF NOT EXISTS contract_usage_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP;

CREATE TABLE IF NOT EXISTS contract_kb_document (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    document_id BIGINT NOT NULL,
    usage_type VARCHAR(40) NOT NULL DEFAULT 'CONTRACT_AGENT_CONTEXT',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_contract_kb_document (case_id, document_id),
    KEY idx_contract_kb_document (document_id, case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
