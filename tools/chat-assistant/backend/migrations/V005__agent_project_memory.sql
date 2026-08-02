-- Agent 项目记忆表（情节记忆 + 已确认事实）
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
