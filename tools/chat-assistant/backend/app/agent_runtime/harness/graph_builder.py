"""Common graph lifecycle builder (PRD Phase 4, task 2).

``build_task_graph`` turns a TaskSpec into a compiled LangGraph. The spec's
§6.1 role hooks are the single source of truth for the node inventory; the
builder wires the lifecycle skeleton around them:

* the ``context`` role receives the START edge (PRD §4.2 load_snapshot +
  build_task_context are the shared base every task graph starts from);
* explicit ``edges`` and ``conditional_routes`` declare the differences;
* the ``persistence`` role's last stage flows to END;
* ``human_gate``, when declared, is registered as its stage's node.

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
    stages = spec.stages
    if not stages:
        raise ValueError(f"TaskSpec {spec.graph_name} declares no stages")

    # Roles must partition the stage space: one role repeating a stage and
    # two roles sharing one are both wiring mistakes and fail fast here.
    seen_roles: dict[str, str] = {}
    for role_name in (
        "context", "planner", "retriever", "analyzer", "validator",
        "coverage_auditor", "composer", "persistence",
    ):
        role_seen: set[str] = set()
        for stage_name, _fn in getattr(spec, role_name).stages:
            if stage_name in role_seen:
                raise ValueError(
                    f"TaskSpec {spec.graph_name}: role {role_name} declares "
                    f"stage {stage_name} more than once"
                )
            if stage_name in seen_roles:
                raise ValueError(
                    f"TaskSpec {spec.graph_name}: stage {stage_name} declared by two roles"
                )
            role_seen.add(stage_name)
            seen_roles[stage_name] = role_name

    if spec.human_gate is not None:
        gate_stage = spec.human_gate.stage
        if gate_stage not in stages:
            raise ValueError(
                f"TaskSpec {spec.graph_name}: human_gate stage {gate_stage} is not a declared stage"
            )
        if spec.nodes[gate_stage] is not spec.human_gate:
            raise ValueError(
                f"TaskSpec {spec.graph_name}: human_gate must be the node of stage {gate_stage}"
            )

    # The builder owns the context chain (§4.2 shared base): START →
    # context… → first role stage. Specs must not re-declare that wiring.
    context_names = [name for name, _fn in spec.context.stages]
    if not context_names:
        raise ValueError(
            f"TaskSpec {spec.graph_name}: context role must declare at least one stage "
            "(§4.2 load_snapshot + build_task_context are the shared base)"
        )
    context_set = set(context_names)
    first_role = spec.stages[len(context_names)] if len(spec.stages) > len(context_names) else None
    for node_name in spec.conditional_routes:
        if node_name in context_set:
            raise ValueError(
                f"TaskSpec {spec.graph_name}: context stage {node_name} is wired by the builder"
            )

    route_targets: set[str] = set()
    for node_name, (_router, route_map) in spec.conditional_routes.items():
        if node_name not in stages:
            raise ValueError(
                f"TaskSpec {spec.graph_name}: conditional route on unknown stage {node_name}"
            )
        if node_name == stages[-1]:
            raise ValueError(
                f"TaskSpec {spec.graph_name}: last stage {node_name} cannot route conditionally"
            )
        for target in route_map.values():
            if target not in stages:
                raise ValueError(
                    f"TaskSpec {spec.graph_name}: route {node_name} -> unknown node {target}"
                )
            route_targets.add(target)

    for src, dst in spec.edges:
        if src not in stages or dst not in stages:
            raise ValueError(f"TaskSpec {spec.graph_name}: edge {src}->{dst} references unknown node")
        if src in context_set:
            raise ValueError(
                f"TaskSpec {spec.graph_name}: context stage {src} is wired by the builder"
            )
        if src in spec.conditional_routes:
            raise ValueError(
                f"TaskSpec {spec.graph_name}: conditional stage {src} must not declare linear edges"
            )

    # True reachability, not just local in/out degree: a disconnected
    # subgraph (e.g. a b↔c cycle with no path from the start) would
    # otherwise compile and silently drop nodes. The implicit context
    # chain joins the graph for the walk.
    outgoing: dict[str, set[str]] = {name: set() for name in stages}
    incoming: dict[str, set[str]] = {name: set() for name in stages}
    for prev, nxt in zip(context_names, context_names[1:]):
        outgoing[prev].add(nxt)
        incoming[nxt].add(prev)
    if first_role is not None:
        outgoing[context_names[-1]].add(first_role)
        incoming[first_role].add(context_names[-1])
    for src, dst in spec.edges:
        outgoing[src].add(dst)
        incoming[dst].add(src)
    for node_name, (_router, route_map) in spec.conditional_routes.items():
        outgoing[node_name].update(route_map.values())
        for target in route_map.values():
            incoming[target].add(node_name)

    reachable: set[str] = {stages[0]}
    frontier = [stages[0]]
    while frontier:
        current = frontier.pop()
        for nxt in outgoing.get(current, ()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    unreachable = [name for name in stages if name not in reachable]
    if unreachable:
        raise ValueError(
            f"TaskSpec {spec.graph_name}: stages unreachable from START: {unreachable}"
        )

    can_end: set[str] = {stages[-1]}
    frontier = [stages[-1]]
    while frontier:
        current = frontier.pop()
        for prev in incoming.get(current, ()):
            if prev not in can_end:
                can_end.add(prev)
                frontier.append(prev)
    dead_ends = [name for name in stages if name not in can_end]
    if dead_ends:
        raise ValueError(
            f"TaskSpec {spec.graph_name}: stages that can never reach END: {dead_ends}"
        )


def build_task_graph(spec: TaskSpec, checkpointer: Any = None) -> Any:
    """Compile a StateGraph from a TaskSpec.

    The context role receives the START edge and chains linearly; the rest
    of the wiring follows ``spec.edges`` verbatim (a stage with a declared
    conditional route has no linear outgoing edge — its route map replaces
    it); the last stage flows to END. ``human_gate``, when declared, is its
    stage's node function (identity validated in ``_validate_spec``), so the
    role-declaration loop below already registers it.
    """
    _validate_spec(spec)
    builder = StateGraph(BaseGraphState)
    for name in spec.stages:
        builder.add_node(name, spec.nodes[name])

    # Shared lifecycle base (§4.2): context chain from START, then into the
    # first business role stage.
    context_names = [name for name, _fn in spec.context.stages]
    first_role = spec.stages[len(context_names)] if len(spec.stages) > len(context_names) else None
    builder.add_edge(START, context_names[0])
    for prev, nxt in zip(context_names, context_names[1:]):
        builder.add_edge(prev, nxt)
    if first_role is not None:
        builder.add_edge(context_names[-1], first_role)

    for src, dst in spec.edges:
        builder.add_edge(src, dst)
    for node_name, (router, route_map) in spec.conditional_routes.items():
        builder.add_conditional_edges(node_name, router, dict(route_map))
    builder.add_edge(spec.stages[-1], END)
    return builder.compile(checkpointer=checkpointer) if checkpointer else builder.compile()
