"""Builders for ``_meta.next_commands`` entries: ready-to-call ``{tool, arguments}`` steps."""

from __future__ import annotations

from typing import Any


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def default_error_next_commands(
    tool: str, error_code: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """A sensible recovery step for any error lacking an explicit fallback."""
    if error_code in ("upstream_unavailable", "rate_limited"):
        return [cmd("get_diagnostics")]
    return [cmd("get_server_capabilities")]
