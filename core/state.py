"""
Agent state definition for LangGraph.

This module defines the central state object that flows through every node
in the graph. Think of it as the agent's "memory".
"""

from typing import TypedDict, Annotated, Any

from core.schemas import (
    EvidenceItem,
    UserIntent,
    MarketStructure,
    SectorRoute,
    FactorEvidence,
    CompositeAssessment,
    StrategyDecision,
    FinalAnswer,
)
from core.constants import AgentStatus


# =============================================================================
# Reducers
# =============================================================================

def _replace(existing: Any, new: Any) -> Any:
    """Replace the existing value entirely."""
    return new


def _append(existing: list | None, new: list | None) -> list:
    """Append new items to the existing list."""
    if existing is None:
        existing = []
    if new is None:
        return existing
    return existing + new


# =============================================================================
# AgentState
# =============================================================================

class AgentState(TypedDict, total=False):
    """
    Central state object for the stock forecast agent graph.
    
    Lifecycle:
        [START]
           │
           ▼  query (set once)
        ┌─────────────────────────────────────────────────────────┐
        │  user_intent               ← intent_clarification_node  │
        │  market_structure          ← market_structure_node      │
        │  sector_route              ← sector_router_node         │
        │  technical_evidence        ← technical_analysis_node    │
        │  fundamental_evidence      ← fundamental_analysis_node  │
        │  capital_evidence          ← capital_analysis_node      │
        │  sentiment_evidence        ← sentiment_analysis_node    │
        │  composite_assessment      ← cross_sector_fusion_node   │
        │  strategy_decision         ← strategy_generation_node   │
        │  final_answer              ← final_answer_node          │
        │  evidence_log (growing)    ← all factor nodes           │
        │  status                    ← various nodes              │
        └─────────────────────────────────────────────────────────┘
           │
           ▼  final_answer or error_message
         [END]
    """
    
    # ===== Input (set once at start) =====
    query: str
    config: dict[str, Any] | None
    
    # ===== Phase 1: Intent & Market Structure =====
    user_intent: Annotated[UserIntent | None, _replace]
    market_structure: Annotated[MarketStructure | None, _replace]
    
    # ===== Phase 2: Sector Routing =====
    sector_route: Annotated[SectorRoute | None, _replace]
    
    # ===== Phase 3: Factor Evidence (one per sector) =====
    technical_evidence: Annotated[FactorEvidence | None, _replace]
    fundamental_evidence: Annotated[FactorEvidence | None, _replace]
    capital_evidence: Annotated[FactorEvidence | None, _replace]
    sentiment_evidence: Annotated[FactorEvidence | None, _replace]
    
    # ===== Phase 4: Fusion & Strategy =====
    composite_assessment: Annotated[CompositeAssessment | None, _replace]
    strategy_decision: Annotated[StrategyDecision | None, _replace]
    
    # ===== Growing logs =====
    evidence_log: Annotated[list[EvidenceItem], _append]
    
    # ===== Final outputs =====
    final_answer: Annotated[FinalAnswer | None, _replace]
    error_message: Annotated[str | None, _replace]
    
    # ===== Status =====
    status: AgentStatus


# =============================================================================
# Factory function
# =============================================================================

def create_initial_state(
    query: str,
    config: dict[str, Any] | None = None,
) -> AgentState:
    """
    Create a valid initial agent state.
    
    Args:
        query: The user's natural language query about a stock
        config: Optional configuration dict
    
    Returns:
        A properly initialized AgentState with all fields set
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    
    return AgentState(
        query=query.strip(),
        config=config,
        # Phase 1
        user_intent=None,
        market_structure=None,
        # Phase 2
        sector_route=None,
        # Phase 3
        technical_evidence=None,
        fundamental_evidence=None,
        capital_evidence=None,
        sentiment_evidence=None,
        # Phase 4
        composite_assessment=None,
        strategy_decision=None,
        # Logs & output
        evidence_log=[],
        final_answer=None,
        error_message=None,
        status=AgentStatus.RUNNING,
    )
