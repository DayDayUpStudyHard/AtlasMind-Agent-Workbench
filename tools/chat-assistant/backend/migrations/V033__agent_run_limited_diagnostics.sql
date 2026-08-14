-- PRD §7.2 / §6.4: LIMITED runs persist their mandatory disclosure on the
-- run row — the stable read entry behind "详见运行诊断" (get_run /
-- get_run_detail return it as limitedDiagnostics).
ALTER TABLE agent_run
  ADD COLUMN IF NOT EXISTS limited_diagnostics JSON NULL AFTER error_message;
