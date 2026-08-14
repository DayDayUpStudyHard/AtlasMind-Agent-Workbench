-- V035: PRD §10 / Phase 8 task 3 — per-run frozen retrieval / rerank /
-- scorer versions. Every evaluation result must be traceable to the exact
-- stack that produced it (acceptance: no constant-1.0 placeholder scoring,
-- every metric traceable to artifact / citation / version).

ALTER TABLE agent_run
  ADD COLUMN IF NOT EXISTS retrieval_version VARCHAR(64) NULL AFTER prompt_version;

ALTER TABLE agent_run
  ADD COLUMN IF NOT EXISTS rerank_version VARCHAR(64) NULL AFTER retrieval_version;

ALTER TABLE agent_run
  ADD COLUMN IF NOT EXISTS scorer_version VARCHAR(64) NULL AFTER rerank_version;
