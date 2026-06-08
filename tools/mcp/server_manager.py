"""
MCP server manager for managing multiple tool servers.

This module manages the lifecycle of multiple MCP server processes:
- Starting all configured servers
- Stopping all servers gracefully
- Providing access to individual MCP clients

Usage:
    manager = MCPServerManager()
    
    # Register server configs
    manager.register_config(MCPServerConfig(...))
    manager.register_config(MCPServerConfig(...))
    
    # Start all servers
    await manager.start_all()
    
    # Get a client for a specific server
    client = manager.get_client("my_tool")
    
    # Stop all servers
    await manager.shutdown_all()
"""

import asyncio

from tools.mcp.schemas import MCPServerConfig
from tools.mcp.client import MCPClient


class MCPServerManager:
    """
    Manager for multiple MCP server processes.
    
    Maintains a registry of server configurations and their
    corresponding MCPClient instances.
    """

    def __init__(self) -> None:
        self._configs: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}

    def register_config(self, config: MCPServerConfig) -> None:
        """
        Register an MCP server configuration.
        
        This does NOT start the server yet. Call start_all() or start()
        to actually launch the processes.
        
        Args:
            config: Server configuration including command and working_dir
        """
        self._configs[config.name] = config

    async def start_all(self) -> None:
        """
        Start all registered MCP servers.
        
        Launches each server process and creates an MCPClient for it.
        """
        tasks = []
        for name, config in self._configs.items():
            client = MCPClient(config)
            self._clients[name] = client
            tasks.append(client.start())
        
        if tasks:
            await asyncio.gather(*tasks)

    async def start(self, name: str) -> None:
        """
        Start a specific MCP server by name.
        
        Args:
            name: Server name
        """
        if name not in self._configs:
            raise ValueError(f"Server '{name}' not registered")
        
        if name not in self._clients:
            client = MCPClient(self._configs[name])
            self._clients[name] = client
        
        await self._clients[name].start()

    async def shutdown_all(self) -> None:
        """
        Stop all MCP servers.
        
        Gracefully shuts down each server process.
        """
        tasks = [client.stop() for client in self._clients.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._clients.clear()

    async def shutdown(self, name: str) -> None:
        """
        Stop a specific MCP server by name.
        
        Args:
            name: Server name
        """
        if name in self._clients:
            await self._clients[name].stop()
            del self._clients[name]

    def get_client(self, name: str) -> MCPClient:
        """
        Get the MCPClient for a specific server.
        
        Args:
            name: Server name
        
        Returns:
            MCPClient instance
        
        Raises:
            ValueError: If server not found
        """
        if name not in self._clients:
            raise ValueError(f"Server '{name}' not started")
        return self._clients[name]

    def list_servers(self) -> list[str]:
        """List all registered server names."""
        return list(self._configs.keys())

    def list_running(self) -> list[str]:
        """List all currently running server names."""
        return list(self._clients.keys())
