-- V016: Store detailed remediation and negotiation advice for review findings.

ALTER TABLE contract_review_finding
    ADD COLUMN IF NOT EXISTS remediation_advice TEXT NULL AFTER impact,
    ADD COLUMN IF NOT EXISTS negotiation_advice TEXT NULL AFTER remediation_advice,
    ADD COLUMN IF NOT EXISTS verification_points JSON NULL AFTER negotiation_advice;
