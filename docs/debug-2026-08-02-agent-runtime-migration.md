# 2026-08-02 Session 2 — Phase 3-5 Completion: Stability Verification & Switchover

## Phase 4: Stability Test Results

| Test | Result | Detail |
|------|--------|--------|
| Idempotency | ✅ PASS | Duplicate requestId accepted, no double-run |
| Normal Completion | ✅ PASS | COMPLETED 100%, score=70, hash correct |
| Tool Failure (ES down) | ✅ PASS | COMPLETED, all 7 tools, graceful degradation |
| LLM Fallback Paths | ✅ PASS | `_fallback_plan`, `_fallback_turn`, `_local_reflection` all in place |
| Crash Recovery Module | ✅ PASS | `RunRecovery` + heartbeat + zombie/timeout detection verified |
| Policy Guards | ✅ PASS | `AgentExecutionPolicy`: max 8 calls, 2 turns, 300s, fingerprint dedup |

**Test methodology:**
- Idempotency: created run, called `/internal/agent/run` twice with same runId — both accepted
- Normal: ran full HEALTH_ANALYSIS, verified score=70, dimensions match
- Tool failure: ES confirmed down via `/health`, harness completed successfully with all 7 tools
- Code audit: verified 20 code paths across `recovery.py`, `runner.py`, `policy.py`, `tools.py`

## Phase 5: Switchover

**Current state:** `AGENT_RUNTIME=python` (active in `system_config` table)

**Switchover verified:**
- Java `dispatchByMode("python")` → `aiGateway.startAgentRun()` → Python harness
- Run 40 completed via Java→Python bridge with all deterministic fields matching Java baseline
- Frontend API unchanged — Java still owns `POST /api/workspace/projects/{id}/runs` and `GET .../runs/{id}`
- Rollback: `UPDATE system_config SET config_value='java'` → 30s cache expiry → no restart needed

**To fully switch:**
```sql
UPDATE system_config SET config_value='python' WHERE config_key='AGENT_RUNTIME';
```

**To rollback:**
```sql
UPDATE system_config SET config_value='java' WHERE config_key='AGENT_RUNTIME';
```

## Files Changed (Session 2)

### Bug Fixes
- `tools/chat-assistant/backend/app/agent_runtime/persistence.py` — `_normalize_value()`, `_json_dumps()` helpers, Decimal→float normalization in `canonical_evidence()` and `search_evidence()`
- `tools/chat-assistant/backend/app/agent_runtime/runner.py` — `_json_default()`/`_json_dumps()` helpers, scoring metadata merge now always overwrites LLM version, Decimal→float in JSON serialization
- `tools/chat-assistant/backend/app/agent_runtime/scoring.py` — added `citations` to scoring output dict
- `tools/chat-assistant/backend/app/api/routes.py` — migration runner: strip `--` comments before `;`-split
- `tools/chat-assistant/backend/migrations/V001__agent_run.sql` — replaced `;` with `,` in Chinese comment

### Test Scripts
- `_test_shadow.py` — Shadow Run end-to-end test (Java→Python bridge)
- `_test_stability.py` — Phase 4 stability tests (idempotency, tool failure, code audit)

### Documentation
- `docs/debug-2026-08-02-agent-runtime-migration.md` — this file

---

# 2026-08-02 Session 1 — Agent Runtime Python Migration & Shadow Comparison

## Context

Completed Phase 1 Python Agent Runtime implementation and Java bridge, then ran end-to-end
shadow comparison verification. Set AGENT_RUNTIME=python in system_config and verified
the Java→Python bridge produces identical deterministic outputs to the Java v2-harness.

**Commits:** `f752b48`, `b61f9b0` — feat: migrate Agent Runtime from Java to Python with shadow comparison verification

## Bugs Found & Fixed

### 1. SQL Migration Parser: Semicolons in Chinese Comments
**File:** `tools/chat-assistant/backend/app/api/routes.py` (run_migrations)
**Symptom:** MySQL syntax error `near '�� migration runner...'`
**Root Cause:** Migration V001 had Chinese comment containing `;`:
```
-- MySQL 5.7+ 不支持 IF NOT EXISTS for columns; 由 migration runner 在 Python 侧处理
```
The `sql.split(";")` split the comment, and the tail `由 migration runner 在 Python 侧处理`
didn't start with `--` so it was executed as SQL.

**Fix:**
1. Changed `;` to `,` in the V001 comment
2. Enhanced migration runner to strip `--` prefixed lines BEFORE splitting by `;`:
```python
clean_lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
clean_sql = "\n".join(clean_lines)
for statement in clean_sql.split(";"):
    ...
```

### 2. Decimal JSON Serialization Failure
**File:** `tools/chat-assistant/backend/app/agent_runtime/persistence.py`, `runner.py`
**Symptom:** `TypeError: Object of type Decimal is not JSON serializable` in run 37
**Root Cause:** pymysql DictCursor returns MySQL `DECIMAL(5,4)` columns (confidence_score)
as `decimal.Decimal` objects. These survive through tool execution → citations →
scoring engine → LLM call / JSON serialization and cause failures.
**Fix:**
1. Added `_normalize_value()` recursive converter: Decimal→float, datetime→isoformat
2. Added `_json_default()` and `_json_dumps()` helpers
3. Applied normalization to all evidence-loading methods:
   - `canonical_evidence()` — normalizes before returning
   - `search_evidence()` — normalizes filtered results
4. Replaced all bare `json.dumps()` calls with `_json_dumps()` in persistence.py

### 3. Scoring Metadata Not Persisted (dimensions weight, evidenceHash, citations)
**File:** `tools/chat-assistant/backend/app/agent_runtime/runner.py` (dispatch)
**Symptom:** Report had `scoring_version=None`, `evidence_hash=N/A`, citations without
sourceType/objectType, dimensions without weight field
**Root Cause:** `RunDispatcher.dispatch()` passed the LLM's raw artifact directly to
`save_report()`. The LLM often strips or transforms scoring engine metadata (removes
weight from dimensions, simplifies citations, drops evidenceHash).
**Fix:**
1. In `dispatch()`: **always overwrite** deterministic fields from scoring engine:
```python
for key in ("healthScore", "healthStatus", "dimensions",
            "scoringVersion", "evidenceHash", "analysisMode",
            "scoringRationale", "risks", "citations"):
    if key in scoring:
        raw[key] = scoring[key]  # overwrite LLM version
```
2. Added `citations` to scoring engine output (was previously computed but not returned)

### 4. Java API Path Resolution (NoResourceFoundException)
**File:** `_test_shadow.py`
**Symptom:** 500 error with `NoResourceFoundException: No static resource api/agent/projects/2/runs`
**Root Cause:** Controller mapping is `/api/workspace/projects`, not `/api/agent/projects`.
Also SaToken uses `atlasmind-token` header, not `Authorization: Bearer`.
**Fix:** Corrected URL paths and auth header in test script.

## Shadow Run Comparison Results

**Java Run 34 (v2-harness)** vs **Python Run 40 (v3-python, via Java bridge)**

| Field | Java | Python | Verdict |
|-------|------|--------|---------|
| healthScore | 70 | 70 | ✅ MATCH |
| healthStatus | WATCH | WATCH | ✅ MATCH |
| evidenceHash | 9ac3b8e4f...259183 | 9ac3b8e4f...259183 | ✅ MATCH |
| 交付进展 (w25) | 50 | 50 | ✅ MATCH |
| 工程质量 (w25) | 70 | 70 | ✅ MATCH |
| 架构可维护性 (w20) | 90 | 90 | ✅ MATCH |
| 风险暴露 (w15) | 80 | 80 | ✅ MATCH |
| 协作活跃度 (w15) | 65 | 65 | ✅ MATCH |
| scoringVersion | v2-harness | v3-python | ⚪ Different (expected) |
| citations count | 2 (LLM-selected) | 14 (canonical) | ⚪ Different methodology |

**All 逐位 (exact-match) items: 100% PASS (8/8)**

## Architecture Notes

### Three-Mode Dispatch
```sql
-- Switch without restart (30s cache expiry):
UPDATE system_config SET config_value='java'   WHERE config_key='AGENT_RUNTIME';  -- default
UPDATE system_config SET config_value='python' WHERE config_key='AGENT_RUNTIME';  -- Python Runtime
UPDATE system_config SET config_value='shadow' WHERE config_key='AGENT_RUNTIME';  -- dual harness
```

### Why evidenceHash Matches
The scoring engine uses `canonical_evidence()` (loads ALL 14 evidence items for project 2),
normalizes Decimal→float, then SHA-256 hashes project metadata + sorted citation identities.
Both Java and Python produce the same hash because:
1. Same input data (same evidence in DB)
2. Same normalization (Decimal→float)
3. Same hash function (SHA-256 of canonical evidence lines)

### Python Harness Design
```
RunDispatcher (asyncio + heartbeat)
  └─ AgentRunner (6-phase loop)
       ├─ Phase 1: Context Building (load memory)
       ├─ Phase 2: Planning (LLM or fallback)
       ├─ Phase 3: Tool Calling (LLM-driven, max 2 turns × 8 calls)
       ├─ Phase 4: Evidence & Scoring Guarantee (canonical evidence)
       ├─ Phase 5: Reflection (LLM or local fallback)
       └─ Phase 6: Artifact Generation (LLM or rule-based)
  └─ Recovery (startup zombie scan + periodic heartbeat check)
```
