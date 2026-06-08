"""
Build and compile the LangGraph stock forecast agent workflow.

This module wires all nodes together into a StateGraph and defines
the conditional edges that create the agent's decision loop.

Phase 2 Graph:
    START → intent_clarification → market_structure → sector_router
                                                          ↓
            technical → fundamental → capital → sentiment → cross_sector_fusion
                                                                          ↓
            final_answer → END
                                              ↓
                                           failure → END
"""

from functools import partial

from langgraph.graph import StateGraph, END

from core.state import AgentState
from core.constants import AgentStatus
from core.logging import log_info, log_error
from planner.base import BasePlanner
from graph.trace import make_traced_node, clear_trace
from graph.nodes import (
    intent_clarification_node,
    market_structure_node,
    sector_router_node,
    technical_analysis_node,
    fundamental_analysis_node,
    capital_analysis_node,
    sentiment_analysis_node,
    cross_sector_fusion_node,
    final_answer_node,
    failure_node,
)


def _route_after_structure(state: AgentState) -> str:
    """Conditional routing after market_structure_node."""
    status = state.get("status")
    if status == AgentStatus.FAILED:
        return "failure"
    return "sector_router"


def build_agent_graph(
    planner: BasePlanner,
    enable_trace: bool = False,
) -> StateGraph:
    """
    Build and compile the Phase 2 stock forecast agent workflow graph.

    Returns:
        A compiled LangGraph ready to be invoked with an AgentState
    """
    log_info("graph_builder", {"event": "building_graph", "phase": 2, "trace": enable_trace})

    if enable_trace:
        clear_trace()

    def bind(node_func, **kwargs):
        wrapped = make_traced_node(node_func, node_func.__name__) if enable_trace else node_func
        return partial(wrapped, **kwargs)

    # Bind planner to all nodes that need it
    bound_intent = bind(intent_clarification_node, planner=planner)
    bound_structure = bind(market_structure_node, planner=planner)
    bound_router = bind(sector_router_node, planner=planner)
    bound_technical = bind(technical_analysis_node, planner=planner)
    bound_fundamental = bind(fundamental_analysis_node, planner=planner)
    bound_capital = bind(capital_analysis_node, planner=planner)
    bound_sentiment = bind(sentiment_analysis_node, planner=planner)
    bound_fusion = bind(cross_sector_fusion_node, planner=planner)
    bound_answer = bind(final_answer_node, planner=planner)
    bound_fail = make_traced_node(failure_node, "failure_node") if enable_trace else failure_node

    # Create graph
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("intent_clarification", bound_intent)
    graph.add_node("market_structure", bound_structure)
    graph.add_node("sector_router", bound_router)
    graph.add_node("technical", bound_technical)
    graph.add_node("fundamental", bound_fundamental)
    graph.add_node("capital", bound_capital)
    graph.add_node("sentiment", bound_sentiment)
    graph.add_node("cross_sector_fusion", bound_fusion)
    graph.add_node("final_answer", bound_answer)
    graph.add_node("failure", bound_fail)

    # Define edges
    graph.set_entry_point("intent_clarification")
    graph.add_edge("intent_clarification", "market_structure")

    # Conditional routing after market_structure
    graph.add_conditional_edges(
        "market_structure",
        _route_after_structure,
        {"sector_router": "sector_router", "failure": "failure"},
    )

    # Sequential factor analysis chain
    graph.add_edge("sector_router", "technical")
    graph.add_edge("technical", "fundamental")
    graph.add_edge("fundamental", "capital")
    graph.add_edge("capital", "sentiment")
    graph.add_edge("sentiment", "cross_sector_fusion")
    graph.add_edge("cross_sector_fusion", "final_answer")

    graph.add_edge("final_answer", END)
    graph.add_edge("failure", END)

    log_info("graph_builder", {"event": "graph_built", "phase": 2})
    return graph.compile()
