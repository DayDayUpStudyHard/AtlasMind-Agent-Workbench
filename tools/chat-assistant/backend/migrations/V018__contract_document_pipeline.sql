-- V018: Contract document pipeline observability and contract private chunks.

CREATE TABLE IF NOT EXISTS contract_document_job (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    document_id BIGINT NOT NULL,
    job_type VARCHAR(64) NOT NULL DEFAULT 'CONTRACT_DOCUMENT_PIPELINE',
    status VARCHAR(64) NOT NULL DEFAULT 'UPLOADED',
    stage VARCHAR(64) NULL,
    progress INT NOT NULL DEFAULT 0,
    error_message TEXT NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_case_job (case_id, create_time),
    INDEX idx_document_job (document_id, create_time),
    INDEX idx_status (status, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS contract_document_job_trace (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id BIGINT NOT NULL,
    stage VARCHAR(64) NOT NULL,
    sequence_no INT NOT NULL,
    summary VARCHAR(500) NOT NULL,
    input_json LONGTEXT NULL,
    output_json LONGTEXT NULL,
    error_message TEXT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_job_seq (job_id, sequence_no),
    INDEX idx_job_stage (job_id, stage, sequence_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS contract_clause_chunk (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    document_id BIGINT NOT NULL,
    clause_id BIGINT NULL,
    clause_number VARCHAR(64) NULL,
    chunk_index INT NOT NULL,
    chunk_text LONGTEXT NOT NULL,
    source_page INT NULL,
    content_hash CHAR(64) NOT NULL,
    embedding_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    index_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_case_chunk (case_id, document_id, chunk_index),
    INDEX idx_clause_chunk (clause_id, chunk_index),
    INDEX idx_embedding_status (embedding_status, index_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS contract_timeline_node (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    document_id BIGINT NULL,
    clause_id BIGINT NULL,
    node_type VARCHAR(64) NOT NULL,
    label VARCHAR(256) NOT NULL,
    node_date DATE NULL,
    condition_text VARCHAR(512) NULL,
    responsible_party VARCHAR(64) NULL,
    business_meaning TEXT NULL,
    citation_json LONGTEXT NULL,
    confidence DECIMAL(5,4) NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'EXTRACTED',
    status VARCHAR(64) NOT NULL DEFAULT 'EXTRACTED',
    manual_override TINYINT NOT NULL DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_case_timeline (case_id, node_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
