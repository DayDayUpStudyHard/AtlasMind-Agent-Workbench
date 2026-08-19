# Real Benchmark Baseline 2026-08-19

This report records the first live comparison on the frozen
`contract-review-v1` dataset.

## Conditions

- Dataset hash: `4ba874b79081ed7ba6cb70a0d126a1deabb1862dcb1521f7fa721f07d475dafa`
- Model: `deepseek-v4-flash`
- Temperature: `0`
- Elasticsearch: required, `http://localhost:19200`
- MySQL retrieval fallback: disabled
- Scorer: `eval-scorers-v2`

## Results

| Run | Runtime | Status | Recall | Dual citation | False positive | Schema | P95 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `56` | Legacy | `COMPLETED` | 66.67% | 100.00% | 0.00% | 100.00% | 66s |
| `57` | LangGraph v1 | `DEGRADED` | 66.67% | 40.71% | 0.00% | 100.00% | unavailable |
| `61` | LangGraph v1 (fixed retrieval diagnostics) | `DEGRADED` | 66.67% | 39.68% | 0.00% | 100.00% | 348s |

Run `61` executed all three cases with the environment probe READY and no
infrastructure-failed cases. The `STANDARD_CLAUSE` diagnostic is now scoped by
domain; it no longer reports a run-wide missing source when another domain has
already retrieved standard clauses. All three cases are still `LIMITED` because
one or more WorkUnits exceed the `maxTokens=16384` budget after real LLM
consumption is accumulated across retry/targeted-retrieval attempts. Latency is
also materially high (P50 221s, P95 348s).

This is not yet a clean LangGraph quality baseline. P3 is paused pending a
decision on the budget policy: lower the per-call analysis cap to make retries
fit within the existing WorkUnit budget, isolate retry spend into a separate
budget, or raise the WorkUnit token budget. No quality gate was relaxed in this
iteration.

## Artifacts

- JSON: `tools/chat-assistant/backend/benchmark-results/contract-review-v1-legacy.json`
- JSON: `tools/chat-assistant/backend/benchmark-results/contract-review-v1-langgraph.json`
- Comparison JSON: `tools/chat-assistant/backend/benchmark-results/contract-review-v1-legacy-vs-langgraph.json`
- Comparison Markdown: `tools/chat-assistant/backend/benchmark-results/contract-review-v1-legacy-vs-langgraph.md`
- Fixed rerun JSON: `tools/chat-assistant/backend/benchmark-results/contract-review-v1-langgraph-fixed2.json`
- Budgeted rerun JSON: `tools/chat-assistant/backend/benchmark-results/contract-review-v1-langgraph-budgeted.json`
- Budgeted compact rerun JSON: `tools/chat-assistant/backend/benchmark-results/contract-review-v1-langgraph-budgeted-compact.json`

Run IDs `56`, `57`, `58`, `61`, `62`, and `63` are persisted in `agent_eval_run`. Run `59`
and `60` stopped at the environment probe because the CLI process inherited the
default `localhost:9200`; the valid host-mapped port is `localhost:19200` via
`ES_HOST`.

## Budgeted rerun findings

After constraining contract-domain analysis to `4096` completion tokens, one
retry, compact evidence payloads, and no duplicate unstructured fallback:

| Run | Status | Recall | Dual citation | P95 | Budget limited |
| --- | --- | ---: | ---: | ---: | ---: |
| `61` | `DEGRADED` | 66.67% | 39.68% | 348s | 3/3 |
| `62` | `DEGRADED` | 100.00% | 45.15% | 558s | 2/3 |
| `63` | `DEGRADED` | 66.67% | 48.53% | 347s | 0/3 |

Run `63` proves that the `maxTokens` budget issue is resolved and latency is
back near the original run, but it encountered DeepSeek `402 Insufficient
Balance`; some domains used deterministic fallback. It is therefore not a
clean semantic quality baseline. A clean rerun requires restoring the LLM
provider balance or switching to an authorized provider with the same pinned
configuration.
