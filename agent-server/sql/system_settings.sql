-- AtlasMind runtime settings
-- Execute with: mysql -u root -p AtlasMind Agent Workbench < agent-server/sql/system_settings.sql

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS sys_setting (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    setting_key VARCHAR(100) NOT NULL,
    setting_value VARCHAR(500) NOT NULL,
    value_type VARCHAR(20) NOT NULL DEFAULT 'STRING',
    description VARCHAR(255),
    editable TINYINT DEFAULT 1,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_setting_key (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO sys_setting (setting_key, setting_value, value_type, description, editable)
VALUES
    ('ai.retrieval.top-k', '5', 'INTEGER', 'AI 默认检索数量', 1),
    ('ai.retrieval.max-top-k', '10', 'INTEGER', 'AI 最大检索数量', 1),
    ('ai.enabled', 'true', 'BOOLEAN', '是否启用用户端 AI', 1)
ON DUPLICATE KEY UPDATE
    description = VALUES(description),
    value_type = VALUES(value_type),
    editable = VALUES(editable);
