-- Rich, expandable risk analysis fields remain grouped so the finding table
-- keeps its stable decision/status columns while the Agent schema can evolve.
ALTER TABLE contract_review_finding
    ADD COLUMN IF NOT EXISTS detail_json JSON NULL AFTER suggested_action;
