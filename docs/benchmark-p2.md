# Reproducible Benchmark P2

P2 makes the P0/P1 benchmark evidence usable in the management UI. It does
not add semantic metrics or reinterpret existing quality scores.

## Evaluation center

The run list and run detail show the P1 operational facts alongside semantic
metrics:

| Surface | Facts shown |
| --- | --- |
| Run list | P95 latency, input/output Tokens, cost availability and estimate |
| Run detail | P50/P95, Token totals, configured cost, execution stack |
| Raw summary | Full `summaryJson.operations` snapshot for audit/export |

Missing data is rendered as `未观测` or `不可用`, never as a zero measurement.
Cost remains unavailable until the run supplied explicit pricing and observed
Token telemetry.

## Agent chain

The management-side Agent run list now displays the actual graph/runtime,
model, and prompt version captured by `agent_run`. This makes a run's chain
visible without relying on raw trace JSON, while detailed node and tool facts
remain available in the observability view.

## Comparison discipline

P2 preserves P0 compatibility guards: only runs with the same dataset hash and
scorer version are comparable by default. P1 operational deltas are presented
beside, never folded into, quality metrics such as recall, citation rate and
false-positive rate.
