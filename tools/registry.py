"""
Tool registry for managing available tools.

The registry maintains a mapping from tool names to tool instances.
It supports both internal tools (direct Python classes) and MCP tools
(adapted from external processes).

Usage:
    registry = ToolRegistry()
    registry.register(MyTool())           # Register an internal tool
    registry.register(mcp_tool_adapter)   # Register an MCP tool
    
    tool = registry.get("my_tool")        # Lookup by name
    specs = registry.list_specs()         # Get all specs for planner
"""

from core.schemas import ToolSpec
from core.errors import ToolExecutionError
from tools.base import BaseTool


class ToolRegistry:
    """
    Registry for managing tools.
    
    Provides:
    - Registration of tools by name
    - Lookup of tools by name
    - Listing all tool specs for the planner
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        Register a tool in the registry.
        
        Args:
            tool: A concrete tool instance
        
        Raises:
            ToolExecutionError: If a tool with the same name already exists
        """
        name = tool.spec.name
        if name in self._tools:
            raise ToolExecutionError(
                f"Tool '{name}' is already registered",
                details={"existing": name}
            )
        self._tools[name] = tool

    def get(self, name: str) -> BaseTool:
        """
        Get a tool by name.
        
        Args:
            name: Tool name
        
        Returns:
            The tool instance
        
        Raises:
            ToolExecutionError: If tool not found
        """
        if name not in self._tools:
            raise ToolExecutionError(
                f"Tool '{name}' not found",
                details={"available": list(self._tools.keys())}
            )
        return self._tools[name]

    def list_specs(self) -> list[ToolSpec]:
        """
        List all registered tool specs.
        
        This is called by the planner's decide() method to know
        what tools are available.
        
        Returns:
            List of ToolSpec objects
        """
        return [tool.spec for tool in self._tools.values()]

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)
