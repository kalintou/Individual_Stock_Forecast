"""
Exception hierarchy for the stock forecast agent framework.

All errors inherit from StockForecastAgentError, allowing callers to catch
agent-specific failures separately from generic Python exceptions.

Structure:
    StockForecastAgentError (base)
    ├── PlannerError       # Planning / analysis failed
    ├── ToolExecutionError # Tool invocation failed
    ├── FusionError        # Evidence fusion failed
    └── StateValidationError # State is missing required fields
"""


class StockForecastAgentError(Exception):
    """
    Base exception for all agent-related errors.

    Args:
        message: Human-readable error description
        details: Optional dict with extra context
    """

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | details={self.details}"
        return self.message


class PlannerError(StockForecastAgentError):
    """Raised when the planner (text LLM) fails to analyze or decide."""
    pass


class ToolExecutionError(StockForecastAgentError):
    """Raised when a tool invocation fails or returns invalid output."""
    pass


class FusionError(StockForecastAgentError):
    """Raised when evidence fusion fails to convert tool results."""
    pass


class StateValidationError(StockForecastAgentError):
    """Raised when the agent state is missing required fields or is malformed."""
    pass
