"""Builders for ``_meta.next_commands`` entries: ready-to-call ``{tool, arguments}`` steps."""

from __future__ import annotations

import unicodedata
from typing import Any


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def safe_echo(value: Any) -> bool:
    """True if a caller value may be repeated in a page/widen step (GTS-CORE-TXT-04):
    strings of at most 200 characters without control/format code points (Unicode Cc/Cf)."""
    if isinstance(value, list | tuple):
        return all(map(safe_echo, value))
    if not isinstance(value, str):
        return True
    return len(value) <= 200 and not any(unicodedata.category(c) in ("Cc", "Cf") for c in value)


def default_error_next_commands(
    tool: str, error_code: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """A sensible recovery step for any error lacking an explicit fallback."""
    if error_code in ("upstream_unavailable", "rate_limited"):
        return [cmd("get_diagnostics")]
    return [cmd("get_server_capabilities")]
