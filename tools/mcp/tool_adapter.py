"""
MCP tool adapter — bridges MCP tools to the agent's BaseTool interface.

This module adapts MCP tools (from external processes) into BaseTool
instances that can be registered in the ToolRegistry and used by the
ToolExecutor.

The adapter:
- Wraps an MCPClient
- Converts MCPTool definitions to ToolSpec
- Converts MCP tool results to ToolResult

This is the bridge between the MCP world and the agent world.
"""

from typing import Any

from tools.base import BaseTool
from core.schemas import ToolSpec, ToolCallRequest, ToolResult
from core.errors import ToolExecutionError
from tools.mcp.client import MCPClient
from tools.mcp.schemas import MCPTool


class MCPToolAdapter(BaseTool):
    """
    Adapter that wraps an MCP tool to make it look like a BaseTool.
    
    This allows MCP tools (running in external processes) to be used
    seamlessly alongside internal Python tools.
    
    Usage:
        client = MCPClient(config)
        await client.start()
        
        mcp_tools = await client.list_tools()
        for mcp_tool in mcp_tools:
            adapter = MCPToolAdapter(client, mcp_tool)
            registry.register(adapter)  # Now it looks like a normal tool!
    """

    def __init__(self, client: MCPClient, mcp_tool: MCPTool) -> None:
        self._client = client
        self._mcp_tool = mcp_tool
        self._spec_cache: ToolSpec | None = None

    @property
    def name(self) -> str:
        """Return the tool name for logging."""
        return f"mcp_{self._mcp_tool.name}"

    @property
    def spec(self) -> ToolSpec:
        """
        Convert MCP tool definition to agent's ToolSpec.
        
        This is what the planner sees when deciding which tool to call.
        """
        if self._spec_cache is None:
            self._spec_cache = ToolSpec(
                name=self._mcp_tool.name,
                description=self._mcp_tool.description,
                input_schema=self._mcp_tool.input_schema,
                tags=["mcp"],
            )
        return self._spec_cache

    def invoke(self, request: ToolCallRequest) -> ToolResult:
        """
        Execute the MCP tool via the client.
        
        This is called by ToolExecutor when the planner decides to use this tool.
        
        Note: This method is synchronous on the surface, but internally
        calls the async MCP client. This is because BaseTool.invoke() must
        match the synchronous interface, while MCPClient.call_tool() is async.
        """
        import asyncio

        coro = self._async_invoke(request)
        
        try:
            # Try asyncio.run() first (no running loop)
            return asyncio.run(coro)
        except RuntimeError:
            # We're already inside a running event loop (e.g., async test)
            # Use the existing loop instead
            try:
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(coro)
            except Exception as e:
                raise ToolExecutionError(
                    f"MCP tool '{self._mcp_tool.name}' failed: {e}",
                    details={"tool": self._mcp_tool.name, "args": request.args}
                ) from e
        except Exception as e:
            raise ToolExecutionError(
                f"MCP tool '{self._mcp_tool.name}' failed: {e}",
                details={"tool": self._mcp_tool.name, "args": request.args}
            ) from e

    async def _async_invoke(self, request: ToolCallRequest) -> ToolResult:
        """Async implementation of invoke."""
        # Call the MCP server
        mcp_result = await self._client.call_tool(
            name=self._mcp_tool.name,
            args=request.args,
        )

        # Convert MCP result to ToolResult
        success = mcp_result.get("success", True)
        output = mcp_result.get("output", mcp_result)
        error_message = mcp_result.get("error") if not success else None

        return ToolResult(
            tool_name=self._mcp_tool.name,
            success=success,
            output=output if isinstance(output, dict) else {"result": output},
            error_message=error_message,
        )
