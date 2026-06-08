"""
Real end-to-end agent execution with full node-level tracing.

This script:
1. Loads real API credentials
2. Builds the agent graph with traced nodes
3. Runs on the specified audio + question
4. Generates:
   - trace.jsonl   (machine-readable, one JSON per line)
   - trace_report.md (human-readable Markdown report)

Usage:
    cd agent-basic
    D:\anaconda3\envs\agent-basic\python.exe tests\total-real-test\run_traced_agent.py \
        --audio "D:\PythonProject\audio-agent\IC0001W0001.wav" \
        --question "请识别这个音频" \
        --api-key sk-xxx
"""

import sys
from pathlib import Path
from functools import partial

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json

from langgraph.graph import StateGraph, END

from core.state import AgentState, create_initial_state
from core.constants import AgentStatus
from frontend import OpenAICompatibleFrontend
from planner import OpenAICompatiblePlanner
from fusion import SimpleFusion
from tools import ToolRegistry, ToolExecutor
from tools.mcp import MCPServerManager
from tools.catalog import register_all_mcp_tools
from graph.nodes import (
    initial_prompt_node,
    frontend_evidence_node,
    initial_plan_node,
    planner_decision_node,
    tool_executor_node,
    evidence_fusion_node,
    evidence_summarization_node,
    final_answer_node,
    failure_node,
)
from graph.builder import _route_after_decision
from traced_nodes import make_traced_node, clear_trace, get_trace_entries, serialize_for_trace


def parse_args():
    parser = argparse.ArgumentParser(description="Run agent with full node tracing")
    parser.add_argument("--audio", required=True, help="Path to audio file")
    parser.add_argument("--question", required=True, help="Question about the audio")
    parser.add_argument("--api-key", required=True, help="API key")
    parser.add_argument("--base-url", default="https://api-2.xi-ai.cn/v1", help="API base URL")
    parser.add_argument("--frontend-model", default="gpt-4o-audio-preview", help="Frontend model")
    parser.add_argument("--planner-model", default="gpt-4o", help="Planner model")
    parser.add_argument("--max-steps", type=int, default=5, help="Max steps")
    parser.add_argument("--output-dir", default=".", help="Where to write trace files")
    parser.add_argument("--skip-mcp", action="store_true", help="Skip MCP tool discovery")
    return parser.parse_args()


def build_traced_graph(planner, frontend, fusion, executor, registry):
    """Build the agent graph with all nodes wrapped for tracing."""
    clear_trace()

    # Wrap every node with tracer
    bound_prompt = partial(
        make_traced_node(initial_prompt_node, "initial_prompt_node"),
        planner=planner,
    )
    bound_frontend = partial(
        make_traced_node(frontend_evidence_node, "frontend_evidence_node"),
        frontend=frontend,
        fusion=fusion,
    )
    bound_plan = partial(
        make_traced_node(initial_plan_node, "initial_plan_node"),
        planner=planner,
    )
    bound_decide = partial(
        make_traced_node(planner_decision_node, "planner_decision_node"),
        planner=planner,
        registry=registry,
    )
    bound_execute = partial(
        make_traced_node(tool_executor_node, "tool_executor_node"),
        executor=executor,
    )
    bound_fuse = partial(
        make_traced_node(evidence_fusion_node, "evidence_fusion_node"),
        fusion=fusion,
    )
    bound_summarize = partial(
        make_traced_node(evidence_summarization_node, "evidence_summarization_node"),
        planner=planner,
    )
    bound_answer = partial(
        make_traced_node(final_answer_node, "final_answer_node"),
        frontend=frontend,
    )
    bound_fail = make_traced_node(failure_node, "failure_node")

    # Build graph (same structure as graph/builder.py)
    graph = StateGraph(AgentState)

    graph.add_node("initial_prompt", bound_prompt)
    graph.add_node("frontend_evidence", bound_frontend)
    graph.add_node("initial_plan", bound_plan)
    graph.add_node("planner_decision", bound_decide)
    graph.add_node("tool_executor", bound_execute)
    graph.add_node("evidence_fusion", bound_fuse)
    graph.add_node("evidence_summarization", bound_summarize)
    graph.add_node("final_answer", bound_answer)
    graph.add_node("failure", bound_fail)

    graph.set_entry_point("initial_prompt")

    graph.add_edge("initial_prompt", "frontend_evidence")
    graph.add_edge("frontend_evidence", "initial_plan")
    graph.add_edge("initial_plan", "planner_decision")

    graph.add_conditional_edges(
        "planner_decision",
        _route_after_decision,
        {
            "evidence_summarization": "evidence_summarization",
            "tool_executor": "tool_executor",
            "failure": "failure",
        },
    )

    graph.add_edge("tool_executor", "evidence_fusion")
    graph.add_edge("evidence_fusion", "planner_decision")
    graph.add_edge("evidence_summarization", "final_answer")
    graph.add_edge("final_answer", END)
    graph.add_edge("failure", END)

    return graph.compile()


def write_jsonl(entries: list[dict], output_dir: Path):
    """Write trace entries to a JSON Lines file."""
    path = output_dir / "trace.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    print(f"[Trace] JSONL written to: {path}")


def write_markdown(entries: list[dict], final_state: dict, output_dir: Path, question: str, audio_path: str):
    """Generate a human-readable Markdown report from trace entries."""
    path = output_dir / "trace_report.md"

    lines = []
    lines.append("# Audio Agent Execution Trace Report")
    lines.append("")
    lines.append(f"- **Question**: {question}")
    lines.append(f"- **Audio**: `{audio_path}`")
    lines.append(f"- **Total Nodes Executed**: {len(entries)}")
    lines.append(f"- **Final Status**: {final_state.get('status', 'unknown')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, entry in enumerate(entries, 1):
        node_name = entry["node"]
        elapsed = entry["elapsed_ms"]
        timestamp = entry["timestamp"]

        lines.append(f"## Step {i}: `{node_name}`")
        lines.append("")
        lines.append(f"- **Timestamp**: {timestamp}")
        lines.append(f"- **Elapsed**: {elapsed} ms")
        lines.append("")

        # Input section
        lines.append("### Input State")
        lines.append("```json")
        lines.append(json.dumps(entry["input"], ensure_ascii=False, indent=2, default=str))
        lines.append("```")
        lines.append("")

        # Output section
        lines.append("### Output Update")
        lines.append("```json")
        lines.append(json.dumps(entry["output"], ensure_ascii=False, indent=2, default=str))
        lines.append("```")
        lines.append("")

        # Special handling for key nodes
        if node_name == "planner_decision_node":
            output = entry.get("output", {})
            decision = output.get("current_decision", {})
            if decision:
                action = decision.get("action", "unknown")
                rationale = decision.get("rationale", "")
                tool = decision.get("selected_tool_name", "")
                lines.append(f"> **Planner Decision**: `{action}`")
                if tool:
                    lines.append(f"> **Selected Tool**: `{tool}`")
                lines.append(f"> **Rationale**: {rationale}")
                lines.append("")

        elif node_name == "tool_executor_node":
            output = entry.get("output", {})
            result = output.get("latest_tool_result", {})
            if result:
                success = result.get("success", False)
                tool_name = result.get("tool_name", "")
                out = result.get("output", {})
                lines.append(f"> **Tool Result**: `{tool_name}` | Success: {success}")
                lines.append(f"> **Output**: `{json.dumps(out, ensure_ascii=False, default=str)}`")
                lines.append("")

        elif node_name == "frontend_evidence_node":
            output = entry.get("output", {})
            fe_out = output.get("initial_frontend_output", {})
            if fe_out:
                caption = fe_out.get("question_guided_caption", "")
                lines.append(f"> **Frontend Caption**: {caption}")
                lines.append("")

        elif node_name == "final_answer_node":
            output = entry.get("output", {})
            final = output.get("final_answer", {})
            if final:
                answer = final.get("answer", "")
                confidence = final.get("confidence", 0)
                lines.append(f"> **Final Answer**: {answer}")
                lines.append(f"> **Confidence**: {confidence}")
                lines.append("")

        lines.append("---")
        lines.append("")

    # Final state summary
    lines.append("## Final State Summary")
    lines.append("```json")
    lines.append(json.dumps(serialize_for_trace(dict(final_state)), ensure_ascii=False, indent=2, default=str))
    lines.append("```")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[Trace] Markdown report written to: {path}")


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Setup] Audio: {args.audio}")
    print(f"[Setup] Question: {args.question}")
    print(f"[Setup] API: {args.base_url}")
    print("")

    # Create real components
    frontend = OpenAICompatibleFrontend(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.frontend_model,
    )
    planner = OpenAICompatiblePlanner(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.planner_model,
    )
    fusion = SimpleFusion()
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    # Auto-discover MCP tools
    server_manager = MCPServerManager()
    if not args.skip_mcp:
        import asyncio
        try:
            asyncio.run(register_all_mcp_tools(registry, server_manager, verbose=True))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(register_all_mcp_tools(registry, server_manager, verbose=True))
    else:
        print("[Setup] Skipping MCP tool discovery")

    print(f"[Setup] Registered {len(registry.list_specs())} tool(s)")
    print("")

    # Build traced graph
    print("[Run] Building traced graph...")
    graph = build_traced_graph(planner, frontend, fusion, executor, registry)
    print("[Run] Graph built.")

    # Create initial state
    initial_state = create_initial_state(
        question=args.question,
        audio_path=args.audio,
        max_steps=args.max_steps,
    )
    print("[Run] Initial state ready.")

    # Run!
    print("[Run] Starting graph.invoke()...")
    print("")
    final_state = graph.invoke(initial_state)
    print("")
    print(f"[Run] Agent finished with status: {final_state.get('status')}")
    print("")

    # Generate trace reports
    entries = get_trace_entries()
    write_jsonl(entries, output_dir)
    write_markdown(entries, final_state, output_dir, args.question, args.audio)

    # Also print final answer to console
    status = final_state.get("status")
    if status == AgentStatus.ANSWERED:
        final_answer = final_state.get("final_answer")
        if final_answer:
            print("=" * 60)
            print("FINAL ANSWER")
            print("=" * 60)
            print(final_answer.answer)
            print("=" * 60)
    elif status == AgentStatus.FAILED:
        print("=" * 60)
        print("AGENT FAILED")
        print("=" * 60)
        print(final_state.get("error_message", "Unknown error"))
        print("=" * 60)

    # Cleanup MCP servers
    if not args.skip_mcp:
        import asyncio
        try:
            asyncio.run(server_manager.shutdown_all())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(server_manager.shutdown_all())


if __name__ == "__main__":
    main()
