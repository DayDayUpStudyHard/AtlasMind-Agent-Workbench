-- V021: Timeline node to fulfillment evidence many-to-many links.

ALTER TABLE contract_document
    ADD COLUMN IF NOT EXISTS deleted TINYINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS contract_timeline_evidence_link (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    timeline_node_id BIGINT NOT NULL,
    document_id BIGINT NOT NULL,
    check_id BIGINT NULL,
    link_source VARCHAR(32) NOT NULL DEFAULT 'AGENT',
    relation_type VARCHAR(64) NOT NULL DEFAULT 'FULFILLMENT_EVIDENCE',
    evidence_version INT NULL,
    evidence_hash VARCHAR(128) NULL,
    snippet TEXT NULL,
    deleted TINYINT NOT NULL DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_node_document_check (timeline_node_id, document_id, check_id),
    KEY idx_case_node (case_id, timeline_node_id, deleted),
    KEY idx_document_node (document_id, timeline_node_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
