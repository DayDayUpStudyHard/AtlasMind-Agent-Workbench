-- File-backed benchmark provenance. The benchmark directory is immutable input;
-- these fields freeze the exact dataset and execution configuration in MySQL.
ALTER TABLE agent_eval_dataset
    ADD COLUMN IF NOT EXISTS dataset_hash CHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS schema_version INT NULL,
    ADD COLUMN IF NOT EXISTS source_uri VARCHAR(1024) NULL,
    ADD COLUMN IF NOT EXISTS published_at DATETIME NULL;

ALTER TABLE agent_eval_run
    ADD COLUMN IF NOT EXISTS dataset_hash CHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS config_hash CHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS profile VARCHAR(32) NULL,
    ADD COLUMN IF NOT EXISTS git_commit CHAR(40) NULL,
    ADD COLUMN IF NOT EXISTS baseline_run_id BIGINT NULL,
    ADD COLUMN IF NOT EXISTS scorer_version VARCHAR(64) NULL;
