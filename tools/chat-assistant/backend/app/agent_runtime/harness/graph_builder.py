"""Common graph lifecycle builder (PRD Phase 4, task 2).

``build_task_graph`` turns a TaskSpec into a compiled LangGraph: node
registration, the declared linear / loop-back edges, the conditional routing
hooks, and the START / END attachment of the lifecycle skeleton (PRD §4.2).
Business modules declare a spec instead of re-implementing this wiring —
the builder is the single place that knows how a task lifecycle compiles.

The builder uses the shared ``BaseGraphState`` and adds node functions by
reference, so business behavior is untouched by the shared wiring.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from ..graph.state import BaseGraphState
from .models import TaskSpec


def _validate_spec(spec: TaskSpec) -> None:
    """Fail fast on spec wiring mistakes — broken graphs must not compile."""
    if not spec.stages:
        raise ValueError(f"TaskSpec {spec.graph_name} declares no stages")
    if len(set(spec.stages)) != len(spec.stages):
        raise ValueError(f"TaskSpec {spec.graph_name} declares duplicate stages")
    missing = [name for name in spec.stages if name not in spec.nodes]
    if missing:
        raise ValueError(f"TaskSpec {spec.graph_name}: stages without nodes: {missing}")
    unknown = [name for name in spec.nodes if name not in spec.stages]
    if unknown:
        raise ValueError(f"TaskSpec {spec.graph_name}: nodes outside stages: {unknown}")

    route_targets: set[str] = set()
    for node_name, (_router, route_map) in spec.conditional_routes.items():
        if node_name not in spec.stages:
            raise ValueError(
                f"TaskSpec {spec.graph_name}: conditional route on unknown stage {node_name}"
            )
        if node_name == spec.stages[-1]:
            raise ValueError(
                f"TaskSpec {spec.graph_name}: last stage {node_name} cannot route conditionally"
            )
        for target in route_map.values():
            if target not in spec.stages:
                raise ValueError(
                    f"TaskSpec {spec.graph_name}: route {node_name} -> unknown node {target}"
                )
            route_targets.add(target)

    for src, dst in spec.edges:
        if src not in spec.stages or dst not in spec.stages:
            raise ValueError(f"TaskSpec {spec.graph_name}: edge {src}->{dst} references unknown node")
        if src in spec.conditional_routes:
            raise ValueError(
                f"TaskSpec {spec.graph_name}: conditional stage {src} must not declare linear edges"
            )

    # Reachability sanity: every non-first stage needs an incoming edge
    # (linear or routed), every non-last stage an outgoing one.
    for name in spec.stages[1:]:
        has_in = any(dst == name for _, dst in spec.edges) or name in route_targets
        if not has_in:
            raise ValueError(f"TaskSpec {spec.graph_name}: stage {name} has no incoming edge")
    for name in spec.stages[:-1]:
        has_out = name in spec.conditional_routes or any(src == name for src, _ in spec.edges)
        if not has_out:
            raise ValueError(f"TaskSpec {spec.graph_name}: stage {name} has no outgoing edge")


def build_task_graph(spec: TaskSpec, checkpointer: Any = None) -> Any:
    """Compile a StateGraph from a TaskSpec.

    Linear wiring follows ``spec.edges`` verbatim; a stage with a declared
    conditional route has no linear outgoing edge (its route map replaces
    it); the first stage receives the START edge and the last stage flows
    to END.
    """
    _validate_spec(spec)
    builder = StateGraph(BaseGraphState)
    for name in spec.stages:
        builder.add_node(name, spec.nodes[name])
    for src, dst in spec.edges:
        builder.add_edge(src, dst)
    for node_name, (router, route_map) in spec.conditional_routes.items():
        builder.add_conditional_edges(node_name, router, dict(route_map))
    builder.add_edge(START, spec.stages[0])
    builder.add_edge(spec.stages[-1], END)
    return builder.compile(checkpointer=checkpointer) if checkpointer else builder.compile()
