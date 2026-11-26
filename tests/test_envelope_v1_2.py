"""Response-Envelope Standard v1.2: every data tool result validates against the schema.

The schema is vendored from berntpopp/genefoundry-envelope, tag v1.2.0.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

import jsonschema
import pytest

from pgscatalog_link.mcp.capabilities import TOOLS

SCHEMA_PATH = pathlib.Path(__file__).parent / "conformance" / "envelope-v1.2.schema.json"
SCHEMA_SHA256 = "c3c47e20d7dd189aac2568fc963b5514d7a5ac2c3e5f21d126f42c96d1ad1ae3"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

#: Ops/meta tools return no upstream data and are outside the v1.2 provenance rule.
META_TOOLS = {"get_server_capabilities", "get_diagnostics"}
DATA_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("resolve_trait", {"query": "diabetes"}),
    ("get_trait", {"trait_id": "MONDO_0004989"}),
    ("search_scores", {"trait_id": "MONDO_0004989"}),
    ("search_scores", {}),
    ("get_score", {"pgs_id": "PGS000001"}),
    ("get_score_performance", {"pgs_id": "PGS000001"}),
    ("get_score_performance", {"pgs_id": "PGS000001", "response_mode": "full"}),
    ("get_publication", {"publication": "PGP000001"}),
]


def test_vendored_schema_is_the_pinned_release() -> None:
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == SCHEMA_SHA256


def test_every_data_tool_is_covered() -> None:
    assert {name for name, _ in DATA_CALLS} == set(TOOLS) - META_TOOLS


@pytest.mark.parametrize(("tool", "arguments"), DATA_CALLS)
async def test_data_tool_result_validates(
    facade: Any, call_tool: Any, tool: str, arguments: dict[str, Any]
) -> None:
    out = await call_tool(facade, tool, arguments)
    assert out["success"] is True
    jsonschema.validate(out, SCHEMA)
    meta = out["_meta"]
    assert meta["source"] == "pgscatalog" and meta["data_version"] == "2026-10-23"
    assert meta["retrieved_at"].endswith("Z")
    # deprecated top-level copies, kept for one minor release
    assert out["retrieved_at"] == meta["retrieved_at"] and out["data_version"]


async def test_error_result_validates(facade: Any, call_tool: Any) -> None:
    out = await call_tool(facade, "get_trait", {"trait_id": "EFO_0000305"})
    assert out["success"] is False
    jsonschema.validate(out, SCHEMA)


async def test_cache_hit_keeps_the_original_fetch_time(
    facade: Any, call_tool: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter([1_800_000_000.0 + 3600 * i for i in range(100)])
    monkeypatch.setattr("pgscatalog_link.api.client.time.time", lambda: next(clock))
    first = await call_tool(facade, "get_score", {"pgs_id": "PGS000001"})
    again = await call_tool(facade, "get_score", {"pgs_id": "PGS000001"})
    # the clock moves an hour per reading: an equal stamp can only be the stored fetch time
    assert again["_meta"]["retrieved_at"] == first["_meta"]["retrieved_at"]
    assert first["_meta"]["retrieved_at"].startswith("2027-01-15T")


PAGED = {"get_score_performance", "resolve_trait", "search_scores"}


@pytest.mark.parametrize(("tool", "arguments"), DATA_CALLS)
async def test_paged_tools_report_meta_pagination(
    facade: Any, call_tool: Any, tool: str, arguments: dict[str, Any]
) -> None:
    out = await call_tool(facade, tool, arguments)
    if tool not in PAGED:
        assert "pagination" not in out["_meta"]
        return
    page = out["_meta"]["pagination"]
    assert page["total_count"] == out["total"] and page["has_more"] == out["truncated"]
    assert page["next_cursor"] == out.get("next_cursor")
    assert page.get("next_offset") == out.get("next_offset")
