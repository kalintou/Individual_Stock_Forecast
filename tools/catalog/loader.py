"""
MCP tool catalog loader.

Automatically discovers and registers MCP tools from the catalog directory.

Usage:
    from tools.catalog import register_all_mcp_tools
    
    registry = ToolRegistry()
    server_manager = MCPServerManager()
    
    await register_all_mcp_tools(registry, server_manager, verbose=True)
    
    # Now registry contains all MCP tools from catalog/
    # server_manager has all server processes running
"""

import os
from pathlib import Path

from tools.registry import ToolRegistry
from tools.mcp import MCPServerConfig, MCPServerManager, MCPToolAdapter


async def register_all_mcp_tools(
    registry: ToolRegistry,
    server_manager: MCPServerManager,
    catalog_dir: str | None = None,
    verbose: bool = False,
) -> None:
    """
    Discover and register all MCP tools from the catalog directory.
    
    This function:
    1. Scans catalog/ for subdirectories with config.yaml
    2. Reads each config to get server launch command
    3. Registers the server with MCPServerManager
    4. Starts all servers
    5. Lists tools from each server
    6. Creates MCPToolAdapter for each tool
    7. Registers adapters in ToolRegistry
    
    Args:
        registry: ToolRegistry to register tools into
        server_manager: MCPServerManager to manage server processes
        catalog_dir: Path to catalog directory (default: this file's parent dir)
        verbose: Print discovery info
    """
    if catalog_dir is None:
        catalog_dir = str(Path(__file__).parent)
    
    catalog_path = Path(catalog_dir)
    if not catalog_path.exists():
        return
    
    # Find all subdirectories with config.yaml
    configs = []
    for item in catalog_path.iterdir():
        if item.is_dir() and item.name != "__pycache__" and not item.name.startswith("_"):
            config_file = item / "config.yaml"
            if config_file.exists():
                configs.append(item)
    
    if not configs:
        return
    
    # Read each config and register server
    import yaml
    
    for tool_dir in configs:
        config_file = tool_dir / "config.yaml"
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
        except Exception:
            continue
        
        name = config_data.get("name", tool_dir.name)
        server_config = config_data.get("server", {})
        command = server_config.get("command", [])
        working_dir_raw = server_config.get("working_dir", str(tool_dir))
        # Resolve relative working_dir against tool_dir so "." means the tool's own directory
        working_dir_path = Path(working_dir_raw)
        if not working_dir_path.is_absolute():
            working_dir = str(tool_dir / working_dir_path)
        else:
            working_dir = str(working_dir_path)
        env = server_config.get("env", {})
        
        if not command:
            continue
        
        config = MCPServerConfig(
            name=name,
            command=command,
            working_dir=working_dir,
            env=env,
        )
        
        server_manager.register_config(config)
        
        if verbose:
            print(f"[Catalog] Registered MCP server: {name} ({tool_dir})")
    
    # Start all servers
    await server_manager.start_all()
    
    # Discover tools from each server and register adapters
    for server_name in server_manager.list_running():
        client = server_manager.get_client(server_name)
        
        try:
            mcp_tools = await client.list_tools()
        except Exception:
            continue
        
        for mcp_tool in mcp_tools:
            adapter = MCPToolAdapter(client, mcp_tool)
            registry.register(adapter)
            
            if verbose:
                print(f"[Catalog] Registered tool: {mcp_tool.name} from {server_name}")
