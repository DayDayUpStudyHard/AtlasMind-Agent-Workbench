"""Contract Agent evaluation framework.

Provides dataset loading, test runner, and metrics for measuring
contract review and fulfillment check accuracy.
"""

from .dataset import EvaluationDataset, EvalCase
from .runner import EvaluationRunner
from .metrics import EvaluationMetrics

__all__ = [
    "EvaluationDataset",
    "EvalCase",
    "EvaluationRunner",
    "EvaluationMetrics",
]
