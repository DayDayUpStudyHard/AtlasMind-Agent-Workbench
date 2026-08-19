-- Release-gated evaluation runs may be promoted as the active production baseline.
ALTER TABLE agent_eval_run
    ADD COLUMN IF NOT EXISTS is_production_baseline TINYINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS promoted_at DATETIME NULL;
