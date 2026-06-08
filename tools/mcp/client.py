"""
MCP client for communicating with external tool servers.

The client:
1. Launches an MCP server as a subprocess
2. Communicates via stdin/stdout using JSON-RPC
3. Sends requests (tools/list, tools/call)
4. Receives responses

This is the core of the MCP infrastructure.
"""

import asyncio
import json
import subprocess
from typing import Any

from tools.mcp.schemas import (
    MCPServerConfig,
    MCPTool,
    JSONRPCRequest,
    JSONRPCResponse,
)


class MCPClient:
    """
    Client for communicating with an MCP server process.
    
    Usage:
        config = MCPServerConfig(
            name="my_tool",
            command=["python", "server.py"],
            working_dir="./tools/catalog/my_tool",
        )
        
        client = MCPClient(config)
        await client.start()
        
        tools = await client.list_tools()
        result = await client.call_tool("my_tool", {"audio_path": "test.wav"})
        
        await client.stop()
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """
        Start the MCP server subprocess.
        
        Launches the server with the configured command and working directory.
        """
        if self._process is not None:
            return

        # Launch subprocess with stdin/stdout pipes for JSON-RPC
        self._process = subprocess.Popen(
            self._config.command,
            cwd=self._config.working_dir,
            env={**self._config.env},  # Inherit parent env + custom vars
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )

        # Give the server a moment to initialize
        await asyncio.sleep(0.5)

    async def stop(self) -> None:
        """
        Stop the MCP server subprocess.
        
        Sends a shutdown request, then terminates the process.
        """
        if self._process is None:
            return

        try:
            # Try graceful shutdown via JSON-RPC
            await self._send_request("shutdown", {})
        except Exception:
            pass

        # Terminate the process
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()

        self._process = None

    async def list_tools(self) -> list[MCPTool]:
        """
        List available tools from the MCP server.
        
        Returns:
            List of MCPTool definitions
        """
        response = await self._send_request("tools/list", {})
        result = response.result or {}
        tools_data = result.get("tools", [])
        return [MCPTool(**tool) for tool in tools_data]

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool on the MCP server.
        
        Args:
            name: Tool name
            args: Tool arguments
        
        Returns:
            Tool result dict
        """
        response = await self._send_request(
            "tools/call",
            {"name": name, "arguments": args},
        )
        if response.error:
            raise RuntimeError(f"Tool call failed: {response.error}")
        return response.result or {}

    async def _send_request(self, method: str, params: dict[str, Any]) -> JSONRPCResponse:
        """
        Send a JSON-RPC request and wait for response.
        
        This is the core communication method.
        """
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError("MCP server process is not running")

        async with self._lock:
            self._request_id += 1
            request = JSONRPCRequest(
                id=self._request_id,
                method=method,
                params=params,
            )

            # Serialize and send
            request_line = request.model_dump_json() + "\n"
            self._process.stdin.write(request_line)
            self._process.stdin.flush()

            # Read response line
            response_line = self._process.stdout.readline()
            if not response_line:
                raise RuntimeError("MCP server closed connection")

            # Parse response
            data = json.loads(response_line.strip())
            return JSONRPCResponse(**data)
