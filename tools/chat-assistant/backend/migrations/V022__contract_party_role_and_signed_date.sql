-- V022: Store contract signing date and selected party side.

ALTER TABLE contract_case
    ADD COLUMN IF NOT EXISTS signed_date DATE NULL,
    ADD COLUMN IF NOT EXISTS our_side VARCHAR(8) NULL COMMENT 'A|B from contract party labels';
