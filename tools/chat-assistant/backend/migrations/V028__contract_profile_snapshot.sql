-- V028: Dynamic contract profile generated from the shared evidence snapshot.
-- The profile is intentionally JSON because each contract family exposes a
-- different set of business facts. Base facts are still validated by the
-- extraction graph; type-specific groups are discovered by the LLM.

ALTER TABLE contract_extraction_snapshot
    ADD COLUMN IF NOT EXISTS profile_schema_version VARCHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS profile_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS profile_hash VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS profile_status VARCHAR(32) NULL;

CREATE INDEX idx_extraction_snapshot_profile
    ON contract_extraction_snapshot (case_id, document_id, profile_status, update_time);
