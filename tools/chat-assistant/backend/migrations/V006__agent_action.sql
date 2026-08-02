-- Agent 动作提案表（Python 创建 PENDING_APPROVAL，Java 审批执行）
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
