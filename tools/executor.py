"""
Tool executor for running tool invocations.

The executor takes a ToolCallRequest, looks up the tool in the registry,
and executes it. It handles error wrapping and result formatting.

This is used by the tool_executor_node in the graph.
"""

from core.schemas import ToolCallRequest, ToolResult
from core.errors import ToolExecutionError
from core.logging import log_info
from tools.registry import ToolRegistry


class ToolExecutor:
    """
    Executor that runs tool invocations.
    
    The executor is a thin wrapper around the registry that:
    1. Looks up the tool by name
    2. Validates the request
    3. Executes the tool
    4. Wraps the result
    
    Args:
        registry: ToolRegistry containing available tools
    """

    def __init__(self, registry: ToolRegistry) -> None:
        if registry is None:
            raise ValueError("registry cannot be None")
        self._registry = registry

    async def execute(self, request: ToolCallRequest) -> ToolResult:
        """
        Execute a tool call request.
        
        This method is async because MCP tools may need async communication.
        For internal (Python) tools, the invoke() call is synchronous but
        wrapped in async for uniform interface.
        
        Args:
            request: ToolCallRequest with tool_name, args, context
        
        Returns:
            ToolResult from the tool execution
        
        Raises:
            ToolExecutionError: If tool not found or execution fails
        """
        tool_name = request.tool_name
        
        log_info("tool_executor", {"tool": tool_name, "args": request.args})
        
        # Step 1: Look up the tool
        try:
            tool = self._registry.get(tool_name)
        except ToolExecutionError:
            raise
        
        # Step 2: Validate the request
        tool.validate_request(request)
        
        # Step 3: Execute
        import time
        start_time = time.time()
        
        try:
            # MCP adapters may need async invocation when already inside an event loop
            if hasattr(tool, "_async_invoke"):
                result = await tool._async_invoke(request)
            else:
                result = tool.invoke(request)
        except ToolExecutionError:
            raise
        except Exception as e:
            raise ToolExecutionError(
                f"Tool '{tool_name}' execution failed: {e}",
                details={"tool_name": tool_name, "args": request.args}
            ) from e
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Step 4: Attach metadata if not present
        if result.execution_time_ms == 0:
            result.execution_time_ms = elapsed_ms
        
        log_info("tool_executor", {
            "tool": tool_name,
            "success": result.success,
            "elapsed_ms": elapsed_ms,
        })
        
        return result
