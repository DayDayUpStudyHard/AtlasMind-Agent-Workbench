"""Contract Agent evaluation framework.

Provides dataset loading, test runner, and metrics for measuring
contract review and fulfillment check accuracy.
"""

from .benchmark import BenchmarkDataset, BenchmarkDatasetError, load_benchmark_dataset
from .dataset import EvaluationDataset, EvalCase
from .runner import EvaluationRunner
from .metrics import EvaluationMetrics
from .versioning import EVAL_SCORER_VERSION

__all__ = [
    "EvaluationDataset",
    "EvalCase",
    "EvaluationRunner",
    "EvaluationMetrics",
    "BenchmarkDataset",
    "BenchmarkDatasetError",
    "load_benchmark_dataset",
    "EVAL_SCORER_VERSION",
]
