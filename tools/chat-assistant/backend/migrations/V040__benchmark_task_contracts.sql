-- Benchmark schema v2: task-specific gold labels and their review lifecycle.
-- Real contract content stays in the ignored private corpus; this database only
-- stores the snapshot used by a locally executed benchmark.
ALTER TABLE agent_eval_dataset
    ADD COLUMN IF NOT EXISTS benchmark_profile_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS label_status VARCHAR(32) NOT NULL DEFAULT 'PROVISIONAL',
    ADD COLUMN IF NOT EXISTS private_corpus TINYINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS target_case_count INT NOT NULL DEFAULT 0;

ALTER TABLE agent_eval_case
    ADD COLUMN IF NOT EXISTS expected_output_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS annotation_status VARCHAR(32) NOT NULL DEFAULT 'PROVISIONAL',
    ADD COLUMN IF NOT EXISTS source_case_id BIGINT NULL,
    ADD COLUMN IF NOT EXISTS source_document_id BIGINT NULL,
    ADD COLUMN IF NOT EXISTS source_document_hash CHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS candidate_label_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS label_provider VARCHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS label_model VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS label_prompt_version VARCHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS reviewed_at DATETIME NULL;
