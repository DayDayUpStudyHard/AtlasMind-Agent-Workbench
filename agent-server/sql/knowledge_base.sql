-- AtlasMind Agent Workbench 企业知识库 RAG 扩展表
-- 执行方式：mysql -u root -p123456 AtlasMind Agent Workbench < agent-server/sql/knowledge_base.sql

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS kb_space (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    icon VARCHAR(50),
    color VARCHAR(30),
    sort INT DEFAULT 0,
    enabled TINYINT DEFAULT 1,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted TINYINT DEFAULT 0,
    INDEX idx_enabled_deleted (enabled, deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kb_document (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    space_id BIGINT NOT NULL,
    title VARCHAR(200) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    file_size BIGINT DEFAULT 0,
    file_path VARCHAR(500) NOT NULL,
    status VARCHAR(30) DEFAULT 'UPLOADED',
    parse_mode VARCHAR(20) DEFAULT 'OCR',
    chunk_count INT DEFAULT 0,
    embedding_model VARCHAR(100),
    embedding_dim INT DEFAULT 2560,
    index_name VARCHAR(100) DEFAULT 'kb_chunks',
    last_index_time DATETIME NULL,
    error_message TEXT,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted TINYINT DEFAULT 0,
    INDEX idx_space_status (space_id, status),
    INDEX idx_deleted (deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kb_document_chunk (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    document_id BIGINT NOT NULL,
    space_id BIGINT NOT NULL,
    chunk_index INT NOT NULL,
    section_title VARCHAR(255),
    source_page INT NULL,
    chunk_text LONGTEXT NOT NULL,
    char_count INT DEFAULT 0,
    token_count INT DEFAULT 0,
    embedding_status VARCHAR(30) DEFAULT 'PENDING',
    index_status VARCHAR(30) DEFAULT 'PENDING',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted TINYINT DEFAULT 0,
    INDEX idx_document (document_id),
    INDEX idx_space_document (space_id, document_id),
    INDEX idx_deleted (deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kb_ingest_job (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    document_id BIGINT NOT NULL,
    job_type VARCHAR(30) NOT NULL DEFAULT 'IMPORT',
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    progress INT DEFAULT 0,
    message VARCHAR(500),
    error_message TEXT,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_document (document_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kb_notification (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    type VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    content VARCHAR(1000),
    related_type VARCHAR(30),
    related_id BIGINT,
    read_status TINYINT DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_read_create (read_status, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kb_qa_session (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(30) DEFAULT 'FRONT',
    scope VARCHAR(50) DEFAULT 'GLOBAL',
    owner_token VARCHAR(64) NOT NULL,
    space_id BIGINT NULL,
    document_id BIGINT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kb_qa_message (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id BIGINT NOT NULL,
    role VARCHAR(20) NOT NULL,
    content LONGTEXT NOT NULL,
    model VARCHAR(100),
    latency_ms BIGINT,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kb_retrieval_trace (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    message_id BIGINT NOT NULL,
    query TEXT NOT NULL,
    retrieval_type VARCHAR(50),
    top_k INT DEFAULT 5,
    latency_ms BIGINT,
    fallback_reason VARCHAR(500),
    hit_count INT DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_message (message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kb_retrieval_hit (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trace_id BIGINT NOT NULL,
    source_type VARCHAR(30) NOT NULL,
    source_id BIGINT NOT NULL,
    chunk_id BIGINT NULL,
    title VARCHAR(255),
    score DOUBLE DEFAULT 0,
    snippet TEXT,
    rank_no INT DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kb_tool_call (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trace_id BIGINT NOT NULL,
    name VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL,
    latency_ms BIGINT DEFAULT 0,
    input_summary VARCHAR(1000),
    output_summary VARCHAR(1000),
    error_message TEXT,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kb_eval_case (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    question VARCHAR(1000) NOT NULL,
    expected_source_type VARCHAR(30),
    expected_source_id BIGINT,
    expected_keywords VARCHAR(1000),
    expected_points TEXT,
    enabled TINYINT DEFAULT 1,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 默认知识空间：避免第一次进入后台知识库时为空。
INSERT INTO kb_space (name, description, icon, color, sort, enabled, deleted)
SELECT '项目复盘', '项目 Debug 记录、架构决策和复盘资料', 'bug', '#2563eb', 0, 1, 0
WHERE NOT EXISTS (SELECT 1 FROM kb_space WHERE name = '项目复盘' AND deleted = 0);

INSERT INTO kb_space (name, description, icon, color, sort, enabled, deleted)
SELECT '学习笔记', '日常学习资料、技术文章摘录和知识点整理', 'book', '#10b981', 10, 1, 0
WHERE NOT EXISTS (SELECT 1 FROM kb_space WHERE name = '学习笔记' AND deleted = 0);

INSERT INTO kb_space (name, description, icon, color, sort, enabled, deleted)
SELECT '面试题库', '面试八股、项目问答和复习材料', 'target', '#7c3aed', 20, 1, 0
WHERE NOT EXISTS (SELECT 1 FROM kb_space WHERE name = '面试题库' AND deleted = 0);
