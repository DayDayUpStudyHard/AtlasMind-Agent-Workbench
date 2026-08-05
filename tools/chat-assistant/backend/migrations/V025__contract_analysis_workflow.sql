-- V025: Link document parsing, human confirmation, and contract risk review.

CREATE TABLE IF NOT EXISTS contract_analysis_workflow (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    intake_id BIGINT NULL,
    document_id BIGINT NULL,
    document_version INT NULL,
    evidence_snapshot_hash VARCHAR(128) NULL,
    confirmed_version INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'PARSING',
    current_stage VARCHAR(64) NOT NULL DEFAULT 'DOCUMENT_PARSE',
    review_run_id BIGINT NULL,
    last_error TEXT NULL,
    confirmed_at DATETIME NULL,
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_analysis_workflow_case (case_id, id),
    KEY idx_analysis_workflow_status (status, update_time),
    KEY idx_analysis_workflow_document (document_id, document_version),
    KEY idx_analysis_workflow_run (review_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='合同解析、人工确认与风险审查的业务流程快照';

ALTER TABLE agent_run
    ADD COLUMN IF NOT EXISTS workflow_id BIGINT NULL,
    ADD COLUMN IF NOT EXISTS workflow_stage VARCHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS evidence_snapshot_hash VARCHAR(128) NULL;

