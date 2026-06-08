"""
Minimal structured logging for the agent.

Instead of a complex logging framework, we use simple print-based helpers
that show what's happening at each step. This is enough for learning and
debugging the agent workflow.

In production, you'd replace these with Python's `logging` module or a
structured logger like `structlog`.
"""

from typing import Any


def log_node_start(node_name: str, context: dict[str, Any] | None = None) -> None:
    """Log when a node starts executing."""
    if context:
        print(f"\n>> [{node_name}] starting | {context}")
    else:
        print(f"\n>> [{node_name}] starting")


def log_node_end(node_name: str, result: dict[str, Any] | None = None) -> None:
    """Log when a node finishes executing."""
    if result:
        print(f"OK [{node_name}] finished | {result}")
    else:
        print(f"OK [{node_name}] finished")


def log_planner_decision(action: str, rationale: str, tool_name: str | None = None) -> None:
    """Log a planner decision in a readable format."""
    if tool_name:
        print(f"[BRAIN] Planner decides: {action} (tool={tool_name})")
    else:
        print(f"[BRAIN] Planner decides: {action}")
    print(f"   rationale: {rationale[:200]}{'...' if len(rationale) > 200 else ''}")


def log_error(node_name: str, error: Exception) -> None:
    """Log an error from a node."""
    print(f"XX [{node_name}] ERROR: {error}")


def log_info(label: str, data: dict[str, Any]) -> None:
    """Log arbitrary info with a label."""
    print(f"II {label}: {data}")
