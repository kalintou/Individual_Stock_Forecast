"""
Graph module: LangGraph workflow assembly.

The graph builder depends on langgraph. Trace helpers are lightweight and can be
imported independently by the API/CLI; build_agent_graph is loaded lazily so
modules such as graph.nodes can still be imported in tooling contexts before
runtime dependencies are installed.
"""

from graph.trace import clear_trace, set_trace_dir, write_traces


def build_agent_graph(*args, **kwargs):
    from graph.builder import build_agent_graph as _build_agent_graph

    return _build_agent_graph(*args, **kwargs)


__all__ = [
    "build_agent_graph",
    "write_traces",
    "set_trace_dir",
    "clear_trace",
]
