"""
Pydantic schemas for structured data throughout the stock forecast agent.

These schemas define explicit contracts between components.
All schemas use Pydantic v2 with strict validation.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# =============================================================================
# Evidence Schemas (通用，保留)
# =============================================================================

class EvidenceItem(BaseModel):
    """
    A single piece of evidence accumulated during agent execution.
    """
    source: str = Field(..., description="Source: 'technical', 'fundamental', 'capital', 'sentiment', etc.")
    content: str = Field(..., description="The evidence content")
    evidence_type: str = Field(default="text", description="Type: text, structured, score, etc.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    score: int = Field(default=0, ge=0, le=100, description="Factor score 0-100")
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


# =============================================================================
# Tool Schemas (通用，保留)
# =============================================================================

class ToolSpec(BaseModel):
    """Specification of a tool."""
    name: str = Field(..., min_length=1, description="Unique tool identifier")
    description: str = Field(..., description="What this tool does")
    input_schema: dict[str, Any] = Field(default_factory=dict, description="Expected input format (JSON schema)")
    output_schema: dict[str, Any] = Field(default_factory=dict, description="Expected output format")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")


class ToolCallRequest(BaseModel):
    """Request to invoke a tool."""
    tool_name: str = Field(..., min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result returned by a tool after execution."""
    tool_name: str = Field(...)
    success: bool = Field(...)
    output: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = Field(default=None)
    execution_time_ms: float = Field(default=0.0)
    timestamp: datetime = Field(default_factory=datetime.now)


class ToolCallRecord(BaseModel):
    """Record of a tool call for history tracking."""
    request: ToolCallRequest
    result: ToolResult
    step_number: int = Field(ge=0)


# =============================================================================
# Stock Forecast Agent Schemas
# =============================================================================

class UserIntent(BaseModel):
    """
    Parsed user intent from the natural language query.
    
    Examples:
    - "帮我看看贵州茅台" → stock_name="贵州茅台", stock_code="600519", intent_type="analysis", time_horizon="medium"
    - "明天茅台能买吗" → stock_name="茅台", intent_type="short_term_trade", time_horizon="short"
    """
    stock_name: str = Field(default="", description="Stock name extracted from query")
    stock_code: str = Field(default="", description="Stock code if identifiable")
    intent_type: str = Field(default="analysis", description="analysis / short_term_trade / long_term_invest / risk_check")
    time_horizon: str = Field(default="medium", description="short / medium / long")
    risk_preference: str = Field(default="moderate", description="conservative / moderate / aggressive")
    clarified_query: str = Field(default="", description="The user's true intent in structured form")
    model_config = {"extra": "forbid"}


class MarketStructure(BaseModel):
    """
    Market structure analysis result.
    
    Determines the stock's position in the current market landscape.
    """
    current_market_themes: list[str] = Field(default_factory=list, description="Current hot market themes/main lines")
    stock_themes: list[str] = Field(default_factory=list, description="Themes/concepts this stock belongs to")
    theme_position: str = Field(default="", description="Position in theme: 龙头/核心标的/前排/后排/跟风")
    market_sentiment: str = Field(default="", description="Overall market sentiment")
    sector_heat_rank: int = Field(default=0, description="Sector heat ranking")
    analysis_summary: str = Field(default="", description="Narrative summary of market positioning")
    model_config = {"extra": "forbid"}


class SectorRoute(BaseModel):
    """
    Conditional routing decision: which factor sectors to analyze.
    
    The planner dynamically decides which factors to run based on user intent.
    """
    sectors: list[str] = Field(default_factory=list, description="List of sectors to analyze: technical/fundamental/capital/sentiment")
    skip_reasons: dict[str, str] = Field(default_factory=dict, description="Reason for skipping each sector")
    analysis_focus: str = Field(default="", description="What the analysis should focus on")
    model_config = {"extra": "forbid"}


class FactorEvidence(BaseModel):
    """
    Evidence from a single factor analysis.
    """
    factor_name: str = Field(..., description="technical / fundamental / capital / sentiment")
    trend_signal: str = Field(default="", description="Bullish / Bearish / Neutral")
    score: int = Field(default=50, ge=0, le=100, description="Factor score 0-100")
    key_findings: list[str] = Field(default_factory=list, description="Key findings from analysis")
    risk_flags: list[str] = Field(default_factory=list, description="Risk alerts")
    raw_data_summary: str = Field(default="", description="Summary of raw data for context")
    model_config = {"extra": "forbid"}


class CompositeAssessment(BaseModel):
    """
    Cross-sector fusion result.
    """
    composite_score: int = Field(default=50, ge=0, le=100)
    trend_direction: str = Field(default="", description="多头 / 空头 / 震荡")
    position_status: str = Field(default="", description="突破 / 回踩 / 高位 / 低位 / 震荡")
    risk_level: str = Field(default="中", description="高 / 中 / 低")
    risk_details: list[str] = Field(default_factory=list)
    summary: str = Field(default="")
    model_config = {"extra": "forbid"}


class StrategyDecision(BaseModel):
    """
    Final strategy decision.
    """
    action: str = Field(default="观望", description="买入 / 加仓 / 持有 / 观望 / 减仓 / 卖出")
    position_ratio: int = Field(default=0, ge=0, le=100, description="Suggested position ratio %")
    stop_loss: str = Field(default="", description="Stop loss suggestion")
    take_profit: str = Field(default="", description="Take profit suggestion")
    holding_period: str = Field(default="", description="Suggested holding period")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")
    model_config = {"extra": "forbid"}


# =============================================================================
# Final Answer Schema (保留并扩展)
# =============================================================================

class FinalAnswer(BaseModel):
    """The final answer produced by the agent."""
    answer: str = Field(..., min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_summary: str = Field(default="")
    reasoning_trace: str = Field(default="")
    timestamp: datetime = Field(default_factory=datetime.now)
