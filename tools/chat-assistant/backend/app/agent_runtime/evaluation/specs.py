"""Task-owned contracts for ContractOps benchmarks.

The evaluation runner has one small interface: look up a task spec, execute
its production task plan, then aggregate the metrics named by that spec.
Task-specific schema, labels and release checks remain local here instead of
being encoded as risk-review fields across the runner and admin UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


BENCHMARK_SCHEMA_VERSION = 2
# v2 is the candidate/private-benchmark release profile.  These are task
# quality gates, not score transforms: lowering them changes publishability,
# never the underlying metric numerator or denominator.


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    kind: str = "rate"  # rate | count
    threshold: float | int | None = None
    operator: str = ">="
    release: bool = True


@dataclass(frozen=True)
class BenchmarkTaskSpec:
    task_type: str
    label: str
    task_plan: tuple[str, ...]
    expected_keys: tuple[str, ...]
    primary_metric: str
    metrics: tuple[MetricSpec, ...]
    minimum_approved_cases: int = 5

    def metric_map(self) -> dict[str, MetricSpec]:
        return {metric.key: metric for metric in self.metrics}


def _rate(key: str, label: str, threshold: float, *, release: bool = True) -> MetricSpec:
    return MetricSpec(key, label, "rate", threshold, ">=", release)


def _max(key: str, label: str, threshold: float | int, *, kind: str = "rate") -> MetricSpec:
    return MetricSpec(key, label, kind, threshold, "<=")


_SPECS: dict[str, BenchmarkTaskSpec] = {
    "CONTRACT_INTAKE": BenchmarkTaskSpec(
        task_type="CONTRACT_INTAKE",
        label="首次合同识别",
        # The production intake facts feed the extraction graph. The benchmark
        # runs that same graph but scores only the required identity fields.
        task_plan=("CONTRACT_ELEMENT_EXTRACTION",),
        expected_keys=("intakeFields",),
        primary_metric="fieldAccuracy",
        metrics=(
            _rate("fieldAccuracy", "基础字段准确率", 0.75),
            _rate("partyRoleAccuracy", "主体角色准确率", 0.80),
            _rate("amountAccuracy", "金额规范化准确率", 0.80),
            _rate("dateAccuracy", "日期准确率", 0.75),
            _rate("contractTitleAccuracy", "合同标题准确率", 0.80),
            _rate("citationCoverage", "原文引用覆盖率", 0.80),
            _rate("schemaValidRate", "Schema 有效率", 0.95),
        ),
    ),
    "CONTRACT_ELEMENT_EXTRACTION": BenchmarkTaskSpec(
        task_type="CONTRACT_ELEMENT_EXTRACTION",
        label="合同要素提取",
        task_plan=("CONTRACT_ELEMENT_EXTRACTION",),
        expected_keys=("elements",),
        primary_metric="fieldRecall",
        metrics=(
            _rate("fieldRecall", "要素召回率", 0.75),
            _rate("valueAccuracy", "要素值准确率", 0.75),
            _rate("citationCoverage", "原文引用覆盖率", 0.80),
            _max("hallucinationRate", "幻觉率", 0.15),
            _rate("schemaValidRate", "Schema 有效率", 0.95),
        ),
    ),
    "TIMELINE_EXTRACTION": BenchmarkTaskSpec(
        task_type="TIMELINE_EXTRACTION",
        label="履约日程提取",
        task_plan=("TIMELINE_EXTRACTION",),
        expected_keys=("timelineNodes",),
        primary_metric="nodeRecall",
        metrics=(
            _rate("nodeRecall", "节点召回率", 0.75),
            _rate("dateAccuracy", "日期准确率", 0.60),
            _rate("conditionRecognitionRate", "条件事件识别率", 0.70),
            _rate("responsiblePartyCoverage", "责任方覆盖率", 0.70),
            _max("hallucinationRate", "虚构节点率", 0.15),
            _rate("schemaValidRate", "Schema 有效率", 0.95),
        ),
    ),
    "CONTRACT_REVIEW": BenchmarkTaskSpec(
        task_type="CONTRACT_REVIEW",
        label="风险审查",
        task_plan=("CONTRACT_REVIEW",),
        expected_keys=("risks",),
        primary_metric="riskRecall",
        metrics=(
            _rate("riskRecall", "风险召回率", 0.75),
            _rate("citationCoverage", "双引用覆盖率", 0.80),
            _max("falsePositiveRate", "误报率", 0.15),
            _rate("severityAccuracy", "严重性准确率", 0.75),
            _rate("schemaValidRate", "Schema 有效率", 0.95),
        ),
    ),
    "FULFILLMENT_CHECK": BenchmarkTaskSpec(
        task_type="FULFILLMENT_CHECK",
        label="履约核验",
        task_plan=("TIMELINE_EXTRACTION", "FULFILLMENT_CHECK"),
        expected_keys=("timelineNodes", "fulfillment"),
        primary_metric="judgementAccuracy",
        metrics=(
            _rate("requirementRecall", "履约要求召回率", 0.75),
            _rate("proofStatusAccuracy", "证据状态准确率", 0.70),
            _rate("judgementAccuracy", "AI 判断准确率", 0.70),
            _rate("aiSuggestionAccuracy", "AI 建议准确率", 0.70),
            _rate("restraintRate", "证据不足克制率", 0.70),
            _rate("humanResultMatch", "人工终审一致率", 0.90),
            _max("aiAutoConfirmViolations", "AI 自动终审违规", 0, kind="count"),
            _rate("schemaValidRate", "Schema 有效率", 0.95),
        ),
    ),
    "COMPREHENSIVE": BenchmarkTaskSpec(
        task_type="COMPREHENSIVE",
        label="综合合同作业",
        task_plan=("CONTRACT_ELEMENT_EXTRACTION", "TIMELINE_EXTRACTION", "CONTRACT_REVIEW"),
        expected_keys=("intakeFields", "elements", "timelineNodes", "risks"),
        primary_metric="workflowCompletionRate",
        metrics=(
            _rate("workflowCompletionRate", "工作流完成率", 0.80),
            _rate("crossStageConsistency", "跨阶段一致性", 0.75),
            _rate("snapshotReuseRate", "证据快照复用率", 0.90),
            _rate("schemaValidRate", "Schema 有效率", 0.95),
        ),
    ),
}

_ALIASES = {
    "RISK_REVIEW": "CONTRACT_REVIEW",
    "INTAKE": "CONTRACT_ELEMENT_EXTRACTION",
    "ELEMENT_EXTRACTION": "CONTRACT_ELEMENT_EXTRACTION",
    "FULFILLMENT_TIMELINE": "TIMELINE_EXTRACTION",
    "FULFILLMENT_VERIFICATION": "FULFILLMENT_CHECK",
}


def normalize_task_type(value: Any) -> str:
    raw = str(value or "CONTRACT_REVIEW").upper().strip()
    return _ALIASES.get(raw, raw)


def get_benchmark_spec(value: Any) -> BenchmarkTaskSpec:
    task_type = normalize_task_type(value)
    try:
        return _SPECS[task_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported benchmark task type: {task_type}") from exc


def list_benchmark_specs() -> tuple[BenchmarkTaskSpec, ...]:
    return tuple(_SPECS.values())


def expected_output(case: Mapping[str, Any]) -> dict[str, Any]:
    """Read schema-v2 gold labels while retaining schema-v1 compatibility."""
    raw = case.get("expected_output_json")
    if isinstance(raw, Mapping):
        return dict(raw)
    if not raw:
        return {}
    import json

    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def legacy_expected_findings(case: Mapping[str, Any], task_type: str) -> list[dict[str, Any]]:
    """Project v2 labels onto the legacy scorer input during migration."""
    output = expected_output(case)
    spec = get_benchmark_spec(task_type)
    if spec.task_type == "FULFILLMENT_CHECK":
        fulfillment = output.get("fulfillment")
        if isinstance(fulfillment, Mapping):
            rows = fulfillment.get("requirements")
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, Mapping)]
    for key in spec.expected_keys:
        values = output.get(key)
        if isinstance(values, list):
            return [dict(item) for item in values if isinstance(item, Mapping)]
    return []
