"""
MCP (Model Context Protocol) data models.

MCP is a protocol for communicating with external tools that run in
isolated processes. This module defines the JSON-RPC message formats
used by the MCP client and server.

Key concepts:
- MCPServerConfig: Configuration for launching an MCP server
- MCPTool: Tool definition from an MCP server
- JSONRPCRequest/Response: The wire format for communication
"""

from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """Configuration for an MCP server process."""
    name: str
    command: list[str]
    working_dir: str = "."
    env: dict[str, str] = Field(default_factory=dict)


class MCPTool(BaseModel):
    """Tool definition as reported by an MCP server."""
    name: str
    description: str
    input_schema: dict = Field(default_factory=dict, alias="inputSchema")


class JSONRPCRequest(BaseModel):
    """JSON-RPC request message."""
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict = Field(default_factory=dict)


class JSONRPCResponse(BaseModel):
    """JSON-RPC response message."""
    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: dict | None = None
    error: dict | None = None
