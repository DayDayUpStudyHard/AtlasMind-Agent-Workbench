-- Agent Run 表（含心跳列）
CREATE TABLE IF NOT EXISTS agent_run (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id BIGINT NOT NULL,
    run_type VARCHAR(40) NOT NULL DEFAULT 'HEALTH_ANALYSIS',
    trigger_type VARCHAR(30) NOT NULL DEFAULT 'MANUAL',
    question VARCHAR(1000),
    input_json LONGTEXT,
    status VARCHAR(40) NOT NULL DEFAULT 'CREATED',
    progress INT DEFAULT 0,
    current_step VARCHAR(120),
    error_message TEXT,
    started_at DATETIME,
    finished_at DATETIME,
    last_heartbeat_at DATETIME,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_project_run (project_id, create_time),
    KEY idx_run_status (status, create_time),
    KEY idx_run_heartbeat (status, last_heartbeat_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 为已有 agent_run 表补加心跳列（幂等：列已存在则忽略）
-- MySQL 5.7+ 不支持 IF NOT EXISTS for columns, 由 migration runner 在 Python 侧处理
