# Reproducible Benchmark P0

`benchmarks/` contains the version-controlled source of truth for evaluation
inputs and expectations. The evaluation database stores immutable snapshots and
the results of individual executions; it is not the source of a benchmark.

## Dataset contract

Each dataset directory has a `manifest.yaml` and one or more YAML case files.
The current schema version is `1`. Case files require a `caseId`,
`contractText`, and `expectedFindings`; each expected finding needs a title and
severity.

The dataset hash is SHA-256 over canonical JSON containing the full manifest
and all parsed cases, sorted by `caseId`. It changes when an input, expected
output, or dataset configuration changes, but not when YAML comments or field
ordering changes.

## Commands

Run from `tools/chat-assistant/backend` after configuring the local services:

```powershell
python -m app.agent_runtime.evaluation.cli validate --dataset ..\..\..\benchmarks\contract-review-v1

python -m app.agent_runtime.evaluation.cli run `
  --dataset ..\..\..\benchmarks\contract-review-v1 `
  --engine langgraph `
  --features '{"temperature":0,"requireElasticsearch":true}' `
  --output benchmark-results\contract-review-v1.json

python -m app.agent_runtime.evaluation.cli compare --left-run 101 --right-run 102
```

`run` applies pending migrations, imports the file-backed dataset once by its
hash, freezes dataset/config/git/scorer metadata on a new evaluation run, and
then invokes the production evaluation worker. `compare` rejects runs with
different dataset or scorer hashes unless `--allow-incompatible` is explicit.

P0 deliberately supports the existing live production evaluator only. A fully
deterministic Fake LLM/Retrieval profile belongs to the later offline Benchmark
phase and must not be presented as an end-to-end model-quality result.
