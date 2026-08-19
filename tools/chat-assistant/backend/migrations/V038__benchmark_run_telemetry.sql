-- Operational facts are separate from semantic evaluation scores.
ALTER TABLE agent_eval_run
    ADD COLUMN IF NOT EXISTS latency_p50_ms BIGINT NULL,
    ADD COLUMN IF NOT EXISTS latency_p95_ms BIGINT NULL,
    ADD COLUMN IF NOT EXISTS token_input_total BIGINT NULL,
    ADD COLUMN IF NOT EXISTS token_output_total BIGINT NULL,
    ADD COLUMN IF NOT EXISTS estimated_cost DECIMAL(18,8) NULL,
    ADD COLUMN IF NOT EXISTS cost_currency VARCHAR(8) NULL,
    ADD COLUMN IF NOT EXISTS cost_status VARCHAR(32) NULL,
    ADD COLUMN IF NOT EXISTS execution_stack_json LONGTEXT NULL;
