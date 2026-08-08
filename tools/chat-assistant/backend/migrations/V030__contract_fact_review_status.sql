-- V030: Human review status for extracted contract facts and timeline nodes.

ALTER TABLE contract_extracted_element
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(32) NULL,
    ADD COLUMN IF NOT EXISTS review_note TEXT NULL,
    ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS reviewed_at DATETIME NULL;

ALTER TABLE contract_timeline_node
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(32) NULL,
    ADD COLUMN IF NOT EXISTS review_note TEXT NULL,
    ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS reviewed_at DATETIME NULL;
