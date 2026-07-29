-- AtlasMind project delivery Agent vertical slice.
-- The Java schema initializer also creates these tables for existing local databases.

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_project_memory (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id BIGINT NOT NULL,
    memory_type VARCHAR(30) NOT NULL,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    source_type VARCHAR(40),
    source_id VARCHAR(120),
    confirmed TINYINT DEFAULT 0,
    confirmed_by VARCHAR(100),
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_project_memory (project_id, memory_type, confirmed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_run (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id BIGINT NOT NULL,
    run_type VARCHAR(40) NOT NULL DEFAULT 'HEALTH_ANALYSIS',
    trigger_type VARCHAR(30) NOT NULL DEFAULT 'MANUAL',
    question VARCHAR(1000),
    status VARCHAR(40) NOT NULL DEFAULT 'CREATED',
    progress INT DEFAULT 0,
    current_step VARCHAR(120),
    error_message TEXT,
    started_at DATETIME,
    finished_at DATETIME,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_project_run (project_id, create_time),
    KEY idx_run_status (status, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_run_step (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL,
    step_order INT NOT NULL,
    role_name VARCHAR(80) NOT NULL,
    step_name VARCHAR(120) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    evidence_summary VARCHAR(1000),
    latency_ms BIGINT DEFAULT 0,
    started_at DATETIME,
    finished_at DATETIME,
    error_message TEXT,
    KEY idx_run_step (run_id, step_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_report (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id BIGINT NOT NULL,
    run_id BIGINT NOT NULL,
    title VARCHAR(240) NOT NULL,
    summary TEXT,
    health_status VARCHAR(30),
    health_score INT DEFAULT 0,
    dimensions_json LONGTEXT,
    risks_json LONGTEXT,
    plan_json LONGTEXT,
    citations_json LONGTEXT,
    report_markdown LONGTEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_report_run (run_id),
    KEY idx_project_report (project_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
