"""
Main entry point for the stock forecast agent.

Usage:
    # Basic analysis
    python main.py --query "帮我看看贵州茅台怎么样" --planner-api-key sk-xxx --planner-base-url https://api.xxx/v1

    # Short-term trade advice
    python main.py --query "明天茅台能买吗" --planner-api-key sk-xxx --planner-base-url https://api.xxx/v1

    # With tracing
    python main.py --query "分析一下宁德时代" --planner-api-key sk-xxx --planner-base-url https://api.xxx/v1 --trace

This script:
1. Loads configuration (.env + CLI args)
2. Creates the planner component
3. Builds the LangGraph workflow (Phase 1)
4. Runs the agent on the given query
5. Prints the final report
6. Optionally writes trace files
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import load_config, AgentConfig
from core.state import create_initial_state
from core.constants import AgentStatus
from core.logging import log_info, log_error
from planner import OpenAICompatiblePlanner
from graph import build_agent_graph, write_traces, set_trace_dir
from graph.trace import clear_trace, get_trace_entries, set_trace_run_id


def create_components(config: AgentConfig):
    """
    Create and wire all agent components.

    Phase 1: Only the planner is needed (for intent clarification
    and market structure analysis).

    Returns:
        Tuple of (planner,)
    """
    log_info("main", {"event": "creating_components"})

    planner = OpenAICompatiblePlanner(
        api_key=config.planner_api_key,
        base_url=config.planner_base_url,
        model=config.planner_model,
    )

    log_info("main", {"event": "components_ready"})
    return planner


def run_agent(config: AgentConfig):
    """
    Run the stock forecast agent on a single user query.

    Args:
        config: Agent configuration with query, api_key, etc.

    Returns:
        Final agent state dictionary
    """
    if not config.is_valid:
        print("Error: Missing required configuration. Need --query, --planner-api-key, and --planner-base-url")
        sys.exit(1)

    # Create components
    planner = create_components(config)

    # Setup trace if enabled
    if config.trace:
        set_trace_dir(config.trace_dir)
        print(f"[Run] Trace enabled. Output dir: {config.trace_dir}")

    # Build graph
    graph = build_agent_graph(
        planner=planner,
        enable_trace=config.trace,
    )

    # Create initial state
    initial_state = create_initial_state(query=config.query, config=config.extra or None)

    # Run!
    log_info("main", {"event": "graph_invoke_start", "query": config.query})
    try:
        final_state = graph.invoke(initial_state)
        log_info("main", {"event": "graph_invoke_end", "status": final_state.get("status")})
    except Exception as e:
        log_error("main", RuntimeError(f"Agent execution failed: {e}"))
        final_state = {"status": "failed", "error_message": str(e)}
    finally:
        if config.trace:
            jsonl_path, md_path = write_traces(config.trace_dir)
            if jsonl_path:
                print(f"[Trace] JSONL: {jsonl_path}")
                print(f"[Trace] Markdown: {md_path}")

    return final_state



def _env_config_for_api(query: str, trace: bool = True, extra: dict | None = None) -> AgentConfig:
    """Build AgentConfig for FastAPI without parsing CLI arguments."""
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=Path(__file__).parent / ".env")
    except Exception:
        pass

    return AgentConfig(
        planner_api_key=os.environ.get("PLANNER_API_KEY", ""),
        planner_base_url=os.environ.get("PLANNER_BASE_URL", ""),
        planner_model=os.environ.get("PLANNER_MODEL", "gpt-4o"),
        query=query,
        trace=trace,
        trace_dir=os.environ.get("TRACE_DIR", "."),
        extra=extra or {},
    )


def run_agent_for_api(
    query: str,
    selected_factors: list[str] | None = None,
    prompt_append: dict[str, str] | None = None,
    trace: bool = True,
    trace_run_id: str | None = None,
) -> dict:
    """
    Run the stock forecast agent for the FastAPI bridge.

    This keeps the CLI behavior intact while allowing the frontend to pass
    selected factors and per-request prompt append content through AgentState.config.
    """
    if trace:
        # Bind this API request to an isolated trace buffer. This prevents live
        # SSE trace rows from different browser sessions or Render workers from
        # being mixed together.
        active_trace_run_id = set_trace_run_id(trace_run_id)
        clear_trace(active_trace_run_id)
    else:
        active_trace_run_id = trace_run_id

    extra = {
        "selected_factors": selected_factors,
        "prompt_append": prompt_append or {},
        "api_request": True,
        "trace_run_id": active_trace_run_id,
    }
    config = _env_config_for_api(query=query, trace=trace, extra=extra)

    if not config.is_valid:
        return {
            "status": "failed",
            "error_message": "后端缺少 PLANNER_API_KEY、PLANNER_BASE_URL 或 query 配置。",
            "trace": [],
        }

    final_state = run_agent(config)
    if trace:
        final_state["trace"] = get_trace_entries(active_trace_run_id)
    return final_state

def print_results(final_state: dict):
    """Pretty-print the agent's final output."""
    status = final_state.get("status")

    print("\n" + "=" * 60)
    print("AGENT RESULT")
    print("=" * 60)

    if status == AgentStatus.ANSWERED:
        final_answer = final_state.get("final_answer")
        if final_answer:
            print(f"\n{final_answer.answer}")
        else:
            print("\nStatus: ANSWERED but no final_answer found")

    elif status == AgentStatus.FAILED:
        error = final_state.get("error_message", "Unknown error")
        print(f"\nAgent failed: {error}")

    else:
        print(f"\nUnexpected final status: {status}")

    evidence_count = len(final_state.get("evidence_log", []))
    print(f"\nEvidence items: {evidence_count}")
    print("=" * 60)


def main():
    """CLI entry point."""
    config = load_config()
    final_state = run_agent(config)
    print_results(final_state)


if __name__ == "__main__":
    main()
