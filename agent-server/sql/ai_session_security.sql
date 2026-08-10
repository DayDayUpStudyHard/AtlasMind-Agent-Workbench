-- AtlasMind AI anonymous session ownership migration
-- Existing installations should execute this once:
-- mysql -u root -p AtlasMind Agent Workbench < agent-server/sql/ai_session_security.sql

SET NAMES utf8mb4;

SET @owner_token_exists := (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'kb_qa_session'
      AND COLUMN_NAME = 'owner_token'
);

SET @owner_token_ddl := IF(
    @owner_token_exists = 0,
    'ALTER TABLE kb_qa_session ADD COLUMN owner_token VARCHAR(64) NULL AFTER scope',
    'SELECT 1'
);

PREPARE owner_token_stmt FROM @owner_token_ddl;
EXECUTE owner_token_stmt;
DEALLOCATE PREPARE owner_token_stmt;

UPDATE kb_qa_session
SET owner_token = REPLACE(UUID(), '-', '')
WHERE owner_token IS NULL OR owner_token = '';

ALTER TABLE kb_qa_session
    MODIFY COLUMN owner_token VARCHAR(64) NOT NULL;

SET @case_id_exists := (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'kb_qa_session'
      AND COLUMN_NAME = 'case_id'
);

SET @case_id_ddl := IF(
    @case_id_exists = 0,
    'ALTER TABLE kb_qa_session ADD COLUMN case_id BIGINT NULL AFTER document_id',
    'SELECT 1'
);

PREPARE case_id_stmt FROM @case_id_ddl;
EXECUTE case_id_stmt;
DEALLOCATE PREPARE case_id_stmt;
