"""
MCP (Model Context Protocol) infrastructure.

This package provides the infrastructure for communicating with
external tools that run in isolated processes via JSON-RPC.

Components:
- schemas: Data models for MCP messages
- client: MCP client for process communication
- server_manager: Manages multiple MCP server lifecycles
- tool_adapter: Adapts MCP tools to BaseTool interface
"""

from tools.mcp.schemas import MCPServerConfig, MCPTool, JSONRPCRequest, JSONRPCResponse
from tools.mcp.client import MCPClient
from tools.mcp.server_manager import MCPServerManager
from tools.mcp.tool_adapter import MCPToolAdapter

__all__ = [
    "MCPServerConfig",
    "MCPTool",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "MCPClient",
    "MCPServerManager",
    "MCPToolAdapter",
]
