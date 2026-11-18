"""Locking regression test for the GeneFoundry Response-Envelope Standard v1.

SUCCESS is a flat ``{"success": True, <payload>, "_meta": {...}}``; FAILURE is a flat
``{"success": False, "error_code", "message", "retryable", "recovery_action", "_meta"}``
returned as an ``isError`` ToolResult -- never a nested ``error: {}``. Checked at the
envelope boundary and end-to-end through real registered tools.
"""

from __future__ import annotations

from typing import Any

from fastmcp.tools import ToolResult

from pgscatalog_link.exceptions import NotFoundError
from pgscatalog_link.mcp.envelope import McpErrorContext, run_mcp_tool

META_KEYS = {"tool", "request_id", "elapsed_ms", "source", "unsafe_for_clinical_use"}


async def _run(*args: Any, **kwargs: Any) -> dict[str, Any]:
    res = await run_mcp_tool(*args, **kwargs)
    if isinstance(res, ToolResult):
        assert res.is_error is True
        assert isinstance(res.structured_content, dict)
        return res.structured_content
    return res


async def test_v1_success_envelope_is_flat_banner() -> None:
    async def call() -> dict[str, Any]:
        return {"results": [], "total": 0}

    out = await _run("search_scores", call)
    assert out["success"] is True and out["total"] == 0
    assert set(out["_meta"]) >= META_KEYS and out["_meta"]["unsafe_for_clinical_use"] is True


async def test_v1_error_envelope_is_flat_never_nested() -> None:
    async def call() -> dict[str, Any]:
        raise NotFoundError("No PGS Catalog score has this ID.", field="pgs_id")

    out = await _run("get_score", call, context=McpErrorContext("get_score"))
    assert out["success"] is False and out["error_code"] == "not_found"
    assert out["message"] and isinstance(out["retryable"], bool) and out["recovery_action"]
    assert out["field"] == "pgs_id" and "error" not in out
    assert META_KEYS - {"elapsed_ms"} <= set(out["_meta"])
    assert out["_meta"]["next_commands"]


async def test_v1_real_tool_success_and_error(facade: Any, call_tool: Any) -> None:
    ok = await call_tool(facade, "get_score", {"pgs_id": "PGS000001"})
    assert ok["success"] is True and "error" not in ok
    bad = await call_tool(facade, "get_score", {"pgs_id": "PGS999999"})
    assert bad["success"] is False and bad["error_code"] == "not_found"
    assert "error" not in bad and bad["_meta"]["unsafe_for_clinical_use"] is True
