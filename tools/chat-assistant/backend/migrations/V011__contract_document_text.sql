-- V011: Add content_text column to contract_document for inline text upload.
-- Supports "pure text" contract upload without a physical file.

ALTER TABLE contract_document
    ADD COLUMN IF NOT EXISTS content_text LONGTEXT NULL COMMENT 'Inline contract text content — used when uploading text directly instead of a file';
