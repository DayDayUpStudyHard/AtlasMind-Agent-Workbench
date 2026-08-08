-- A user-triggered re-extraction must retain the prior fact snapshot as history.
-- The original V026 key allowed only one snapshot for a document/version/prompt
-- tuple, which incorrectly rejected later runs with the same source document.

ALTER TABLE contract_extraction_snapshot
    DROP INDEX uk_extraction_snapshot_input,
    ADD UNIQUE KEY uk_extraction_snapshot_run_input
        (case_id, document_id, content_hash, schema_version, prompt_version,
         retrieval_version, source_run_id);
