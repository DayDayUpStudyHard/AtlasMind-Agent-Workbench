-- V036: Phase 8 fulfillment-verification evaluation fixtures.
--
-- A fulfillment evaluation must keep the contract, the later proof material,
-- target timeline-node selector, expected AI assessment, and controlled human
-- decision separate.  This makes the evaluation exercise the production
-- TIMELINE_EXTRACTION -> FULFILLMENT_CHECK -> resume workflow honestly.

ALTER TABLE agent_eval_case
    ADD COLUMN IF NOT EXISTS fulfillment_evidence_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS target_timeline_selector_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS expected_judgements_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS expected_manual_result VARCHAR(32) NOT NULL DEFAULT '';
