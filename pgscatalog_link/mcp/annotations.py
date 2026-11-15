"""Shared tool annotations: every pgscatalog-link tool is a read-only query of the PGS Catalog."""

from __future__ import annotations

from mcp.types import ToolAnnotations

READ_ONLY_OPEN_WORLD = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
