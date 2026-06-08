"""
Execution tracing for the agent graph.

The original project used one process-wide trace list. That works for a
single CLI run, but it is unsafe for a web API: two streaming requests can run
at the same time and their node traces can be interleaved. This module keeps
backwards-compatible helpers while isolating trace entries by a per-request
run_id stored in thread-local context.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_DEFAULT_TRACE_RUN_ID = "__default__"
_TRACE_ENTRIES_BY_RUN: dict[str, list[dict[str, Any]]] = {}
_TRACE_DIR: Path = Path(".")
_TRACE_LOCK = threading.RLock()
_TRACE_CONTEXT = threading.local()


def set_trace_run_id(run_id: str | None) -> str:
    """Set the trace run id for the current thread and return the normalized id."""
    normalized = str(run_id or _DEFAULT_TRACE_RUN_ID)
    _TRACE_CONTEXT.run_id = normalized
    with _TRACE_LOCK:
        _TRACE_ENTRIES_BY_RUN.setdefault(normalized, [])
    return normalized


def get_trace_run_id() -> str:
    """Return the trace run id bound to the current thread."""
    return getattr(_TRACE_CONTEXT, "run_id", _DEFAULT_TRACE_RUN_ID)


def clear_trace(run_id: str | None = None) -> None:
    """Clear accumulated trace entries for one run id only.

    When run_id is omitted, only the current thread's run is cleared. This
    preserves CLI behavior while preventing one API request from deleting
    another request's live trace.
    """
    target = str(run_id or get_trace_run_id())
    with _TRACE_LOCK:
        _TRACE_ENTRIES_BY_RUN[target] = []


def drop_trace(run_id: str | None = None) -> None:
    """Remove a run's trace buffer after the response has been emitted."""
    target = str(run_id or get_trace_run_id())
    with _TRACE_LOCK:
        _TRACE_ENTRIES_BY_RUN.pop(target, None)


def get_trace_entries(run_id: str | None = None) -> list[dict[str, Any]]:
    """Return all trace entries for one run id."""
    target = str(run_id or get_trace_run_id())
    with _TRACE_LOCK:
        return list(_TRACE_ENTRIES_BY_RUN.get(target, []))


def set_trace_dir(path: str | Path) -> None:
    """Set the directory where trace files will be written."""
    global _TRACE_DIR
    _TRACE_DIR = Path(path)
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)


def _append_trace_entry(entry: dict[str, Any], run_id: str | None = None) -> None:
    target = str(run_id or get_trace_run_id())
    with _TRACE_LOCK:
        _TRACE_ENTRIES_BY_RUN.setdefault(target, []).append(entry)


def _is_likely_base64(s: str) -> bool:
    """Heuristic to detect base64-encoded binary data."""
    if not isinstance(s, str) or len(s) < 100:
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
    return len(set(s) - allowed) <= 2


def serialize_for_trace(obj: Any, depth: int = 0, max_depth: int = 10) -> Any:
    """Serialize objects for tracing, filtering out base64 data."""
    if depth > max_depth:
        return "<max depth reached>"

    if isinstance(obj, BaseModel):
        return serialize_for_trace(obj.model_dump(), depth + 1, max_depth)

    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if isinstance(v, str) and _is_likely_base64(v):
                result[k] = f"<base64 data, {len(v)} chars>"
            else:
                result[k] = serialize_for_trace(v, depth + 1, max_depth)
        return result

    if isinstance(obj, list):
        return [serialize_for_trace(item, depth + 1, max_depth) for item in obj]

    if isinstance(obj, bytes):
        return f"<bytes, length={len(obj)}>"

    if isinstance(obj, datetime):
        return obj.isoformat()

    return obj


def make_traced_node(node_func, node_name: str):
    """Wrap a node function to record its execution for the current run id."""
    import time

    def wrapper(state, *args, **kwargs):
        run_id = get_trace_run_id()
        start_time = time.time()
        start_iso = datetime.now().isoformat()

        input_snapshot = serialize_for_trace(dict(state))
        result = node_func(state, *args, **kwargs)
        if result is None:
            result = {}

        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        _append_trace_entry(
            {
                "node": node_name,
                "timestamp": start_iso,
                "elapsed_ms": elapsed_ms,
                "input": input_snapshot,
                "output": serialize_for_trace(result),
            },
            run_id=run_id,
        )
        return result

    wrapper.__name__ = f"traced_{node_name}"
    return wrapper


def write_traces(trace_dir: str | Path | None = None, run_id: str | None = None) -> tuple[Path | None, Path | None]:
    """
    Write trace entries to JSONL and Markdown files.

    Returns:
        (jsonl_path, markdown_path)
    """
    out_dir = Path(trace_dir) if trace_dir else _TRACE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = get_trace_entries(run_id)
    if not entries:
        return None, None

    jsonl_path = out_dir / "trace.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    md_path = out_dir / "trace_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Agent Execution Trace\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        f.write(f"Total nodes: {len(entries)}\n\n")

        for i, entry in enumerate(entries, 1):
            f.write(f"## {i}. {entry['node']}\n\n")
            f.write(f"- Timestamp: {entry['timestamp']}\n")
            f.write(f"- Elapsed: {entry['elapsed_ms']} ms\n\n")
            f.write("### Output\n\n")
            f.write("```json\n")
            f.write(json.dumps(entry.get("output"), ensure_ascii=False, indent=2, default=str))
            f.write("\n```\n\n")

    return jsonl_path, md_path
