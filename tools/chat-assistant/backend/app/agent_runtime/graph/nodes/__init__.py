"""Graph nodes for contract review and fulfillment check graphs.

Each node is a pure function: (state) → partial state update.
Nodes may call LLM, tools, or deterministic code. They must NOT
directly write to MySQL (delegate to persistence nodes).
"""
