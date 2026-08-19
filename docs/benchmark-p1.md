# Reproducible Benchmark P1

P1 adds operational telemetry to the P0 benchmark without changing semantic
quality scores. Every completed evaluation run records the runtime stack used
by its case stages, observed wall-clock latency, node latency, token totals,
rerank/fallback observations, and an explicit cost availability status.

## Operational contract

The `agent_eval_run.summary_json.operations` object is the report contract:

| Field | Meaning |
| --- | --- |
| `latencyP50Ms` / `latencyP95Ms` | P50/P95 of per-case wall-clock duration |
| `latencyTotalMs` | Sum of observed case durations |
| `tokenInputTotal` / `tokenOutputTotal` | Observed node Token totals |
| `estimatedCost` | Estimated price only when explicit pricing and Token telemetry exist |
| `costStatus` | `AVAILABLE` or `UNAVAILABLE` |
| `executionStack` | Distinct runtime, graph, model, prompt, retrieval, rerank and scorer versions |

Missing telemetry is represented as `UNAVAILABLE`/`null`; database defaults of
zero are never interpreted as a measured cost. The semantic fields
`highRiskRecall`, `dualCitationRate`, `falsePositiveRate`, and
`schemaValidRate` remain independent.

## Explicit pricing

Pass pricing as part of `--features` when a cost estimate is desired:

```powershell
python -m app.agent_runtime.evaluation.cli run `
  --dataset ..\..\..\benchmarks\contract-review-v1 `
  --features '{"pricing":{"currency":"USD","inputPerMillion":1,"outputPerMillion":2}}'
```

Model-specific prices can be supplied under `pricing.modelPricing`, with a
`default` entry as fallback. No provider price is inferred by the evaluator.

## Comparable reports

Run comparison returns semantic metrics and an independent `operations`
section with latency, Token and cost deltas. Dataset hash and scorer version
must match unless `--allow-incompatible` is explicitly supplied.

```powershell
python -m app.agent_runtime.evaluation.cli compare `
  --left-run 101 --right-run 102 `
  --format markdown `
  --output benchmark-results\comparison.md
```

The Markdown report is intended for review and portfolio evidence; the JSON
report remains the machine-readable contract for the evaluation center.
