-- V031: Human review records for profile facts that are not backed by element rows.

CREATE TABLE IF NOT EXISTS contract_fact_review (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    fact_key VARCHAR(128) NOT NULL,
    fact_identity VARCHAR(256) NOT NULL,
    fact_label VARCHAR(256) NULL,
    value_hash VARCHAR(128) NULL,
    review_status VARCHAR(32) NOT NULL DEFAULT 'CONFIRMED',
    review_note TEXT NULL,
    reviewed_by VARCHAR(128) NULL,
    reviewed_at DATETIME NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_case_fact_identity (case_id, fact_identity),
    KEY idx_case_fact_key (case_id, fact_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
