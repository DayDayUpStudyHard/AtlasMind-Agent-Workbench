-- Agent 执行轨迹表
CREATE TABLE IF NOT EXISTS agent_run_trace (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    sequence_no INT NOT NULL,
    summary VARCHAR(500) NOT NULL,
    payload_json LONGTEXT,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_run_trace_sequence (run_id, sequence_no),
    KEY idx_run_trace_type (run_id, event_type, sequence_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
