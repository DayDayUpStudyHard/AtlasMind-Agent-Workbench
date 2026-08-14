-- V034: Extraction snapshot provenance chain (PRD Phase 5, task 7).
--
-- A field-level rerun produces a new snapshot that carries settled elements
-- from its ancestor. base_snapshot_id makes that lineage durable so version
-- history stays traceable even after the ancestor run is cleaned up.

ALTER TABLE contract_extraction_snapshot
    ADD COLUMN IF NOT EXISTS base_snapshot_id BIGINT NULL;

ALTER TABLE contract_extraction_snapshot
    ADD COLUMN IF NOT EXISTS rerun_scope_json TEXT NULL;
