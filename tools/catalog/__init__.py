"""
MCP tool catalog.

This package contains MCP tool implementations and the loader
for auto-discovering tools from the catalog directory.
"""

from tools.catalog.loader import register_all_mcp_tools

__all__ = ["register_all_mcp_tools"]
