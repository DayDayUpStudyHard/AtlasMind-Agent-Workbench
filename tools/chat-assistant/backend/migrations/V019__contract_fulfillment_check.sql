-- V019: Fulfillment verification records linked to contract timeline nodes.

CREATE TABLE IF NOT EXISTS contract_fulfillment_check (
    id                      BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id                 BIGINT NOT NULL,
    timeline_node_id         BIGINT NOT NULL,
    run_id                  BIGINT NULL,
    status                  VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    conclusion              VARCHAR(64) NULL,
    risk_level              VARCHAR(16) NULL,
    confidence_level        VARCHAR(16) NULL,
    summary                 TEXT NULL,
    requirement_json         LONGTEXT NULL,
    evidence_snapshot_json   LONGTEXT NULL,
    missing_evidence_json    LONGTEXT NULL,
    explicit_consequence    TEXT NULL,
    ai_risk                 TEXT NULL,
    suggested_actions_json   LONGTEXT NULL,
    manual_result           VARCHAR(32) NULL,
    manual_note             TEXT NULL,
    confirmed_by            VARCHAR(128) NULL,
    confirmed_at            DATETIME NULL,
    create_time             DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time             DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_case_node (case_id, timeline_node_id, create_time),
    KEY idx_run (run_id),
    KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
