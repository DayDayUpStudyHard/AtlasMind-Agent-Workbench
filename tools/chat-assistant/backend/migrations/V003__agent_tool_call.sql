-- Agent 工具调用记录表
CREATE TABLE IF NOT EXISTS agent_tool_call (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL,
    plan_step_id VARCHAR(80),
    call_id VARCHAR(120) NOT NULL,
    tool_name VARCHAR(80) NOT NULL,
    input_json LONGTEXT,
    output_json LONGTEXT,
    status VARCHAR(30) NOT NULL,
    latency_ms BIGINT DEFAULT 0,
    error_message TEXT,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_agent_tool_call (run_id, call_id),
    KEY idx_agent_tool_call_run (run_id, create_time),
    KEY idx_agent_tool_call_status (tool_name, status, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
