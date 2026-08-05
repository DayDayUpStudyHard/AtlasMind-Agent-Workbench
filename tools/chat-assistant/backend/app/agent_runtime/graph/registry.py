"""Graph registry — versioned graph lookup for runtime routing.

Graphs are registered by name+version and compiled once.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class GraphRegistry:
    """Stores and retrieves compiled LangGraph StateGraphs by name and version."""

    def __init__(self):
        self._graphs: dict[str, Any] = {}  # key: "name@version" → compiled graph
        self._builders: dict[str, Callable] = {}  # key: "name@version" → builder fn

    def register(
        self,
        name: str,
        version: str,
        builder: Callable[[], Any],
    ) -> None:
        """Register a graph builder function.

        The builder will be called on first access to compile the graph.
        """
        key = f"{name}@{version}"
        if key in self._builders:
            logger.warning("Re-registering graph %s", key)
        self._builders[key] = builder
        self._graphs.pop(key, None)  # Clear cached compiled graph

    def get(self, name: str, version: str = "v1") -> Any | None:
        """Get a compiled graph, compiling it if necessary.

        Returns None if the graph is not registered.
        """
        key = f"{name}@{version}"
        if key in self._graphs:
            return self._graphs[key]

        builder = self._builders.get(key)
        if builder is None:
            return None

        try:
            compiled = builder()
            self._graphs[key] = compiled
            logger.info("Compiled graph %s", key)
            return compiled
        except Exception as exc:
            logger.exception("Failed to compile graph %s: %s", key, exc)
            return None

    def list_graphs(self) -> list[dict[str, str]]:
        """List all registered graphs."""
        result = []
        for key in self._builders:
            name, version = key.split("@", 1)
            compiled = key in self._graphs
            result.append({
                "name": name,
                "version": version,
                "compiled": compiled,
            })
        return result

    def remove(self, name: str, version: str) -> None:
        """Remove a graph registration."""
        key = f"{name}@{version}"
        self._builders.pop(key, None)
        self._graphs.pop(key, None)


# Module-level singleton
_registry: GraphRegistry | None = None


def get_graph_registry() -> GraphRegistry:
    """Get or create the module-level graph registry singleton."""
    global _registry
    if _registry is None:
        _registry = GraphRegistry()
    return _registry
