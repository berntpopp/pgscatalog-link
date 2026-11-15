"""PGS Catalog MCP tool registrations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgscatalog_link.mcp.tools.catalog import register_catalog_tools
from pgscatalog_link.mcp.tools.discovery import register_discovery_tools

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_all_tools(mcp: FastMCP) -> None:
    """Register every tool group on a FastMCP instance in canonical order."""
    register_discovery_tools(mcp)
    register_catalog_tools(mcp)
