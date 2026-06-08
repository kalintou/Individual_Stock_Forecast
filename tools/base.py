"""
Abstract base class for tools.

Tools are the agent's interface to external capabilities:
- Models, APIs, databases, file processors, etc.

Each tool must:
- Provide a ToolSpec describing its capabilities
- Implement invoke() to execute the tool
- Return structured ToolResult
"""

from abc import ABC, abstractmethod

from core.schemas import ToolSpec, ToolCallRequest, ToolResult
from core.errors import ToolExecutionError


class BaseTool(ABC):
    """
    Abstract base class for all tools.
    
    A tool is a unit of capability that the planner can decide to invoke.
    Tools are registered in the ToolRegistry and executed by the ToolExecutor.
    
    Concrete implementations might be:
    - Local model wrappers
    - API clients
    - File processors
    """

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """
        Return the tool specification.
        
        The spec is used by:
        - The planner to understand tool capabilities
        - The registry to index tools
        - Validation logic to check inputs/outputs
        """
        raise NotImplementedError

    @abstractmethod
    def invoke(self, request: ToolCallRequest) -> ToolResult:
        """
        Execute the tool with the given request.
        
        Args:
            request: ToolCallRequest containing tool_name, args, and context
        
        Returns:
            ToolResult with success status, output, and metadata
        
        Raises:
            ToolExecutionError: If execution fails
        """
        raise NotImplementedError

    def validate_request(self, request: ToolCallRequest) -> None:
        """
        Validate a request before execution.
        
        Raises:
            ToolExecutionError: If request is invalid
        """
        if request.tool_name != self.spec.name:
            raise ToolExecutionError(
                f"Tool name mismatch: expected '{self.spec.name}', got '{request.tool_name}'",
                details={"expected": self.spec.name, "actual": request.tool_name}
            )
