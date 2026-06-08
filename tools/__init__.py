"""
Tools module: tool system and MCP infrastructure.

This package contains:
- BaseTool: Abstract base class for all tools
- ToolRegistry: Tool registration and lookup
- ToolExecutor: Tool execution
- MCP infrastructure: Client, server manager, tool adapter
- Catalog: Auto-discovery and registration of MCP tools
"""

from tools.base import BaseTool
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.catalog import register_all_mcp_tools

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "ToolExecutor",
    "register_all_mcp_tools",
]
