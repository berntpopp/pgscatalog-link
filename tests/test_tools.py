"""End-to-end MCP tool tests through an in-memory FastMCP client."""

from __future__ import annotations

from typing import Any

from fastmcp import Client

from pgscatalog_link.mcp.capabilities import TOOLS


async def _raw(mcp: Any, name: str, args: dict[str, Any]) -> Any:
    async with Client(mcp) as client:
        return await client.call_tool(name, args, raise_on_error=False)


async def test_registered_tools_match_capabilities_and_are_documented(facade: Any) -> None:
    async with Client(facade) as client:
        tools = await client.list_tools()
    assert [t.name for t in tools] == TOOLS
    for tool in tools:
        props = tool.inputSchema.get("properties", {})
        for name, prop in props.items():
            assert prop.get("description"), f"{tool.name}.{name} lacks a description"
        for name in tool.inputSchema.get("required", []):
            assert props[name].get("examples"), f"{tool.name}.{name} lacks examples"
        assert tool.description and "Signature:" in tool.description
        assert tool.annotations is not None and tool.annotations.readOnlyHint is True
        assert tool.outputSchema is None


async def test_resolve_trait_envelope_and_next_steps(facade: Any, call_tool: Any) -> None:
    out = await call_tool(facade, "resolve_trait", {"query": "diabetes", "limit": 3})
    assert out["success"] is True and out["returned"] == 3
    meta = out["_meta"]
    assert meta["tool"] == "resolve_trait" and meta["source"] == "pgscatalog"
    assert meta["unsafe_for_clinical_use"] is True and "elapsed_ms" in meta
    steps = [c["tool"] for c in meta["next_commands"]]
    assert steps == ["search_scores", "resolve_trait"]
    assert meta["next_commands"][1]["arguments"]["offset"] == 3


async def test_obsolete_trait_is_is_error_not_found(facade: Any) -> None:
    res = await _raw(facade, "get_trait", {"trait_id": "EFO_0000305"})
    assert res.is_error is True
    body = res.structured_content
    assert body["error_code"] == "not_found" and body["field"] == "trait_id"


async def test_search_scores_paging_suggests_next_page(facade: Any, call_tool: Any) -> None:
    out = await call_tool(facade, "search_scores", {"trait_id": "MONDO_0004989", "limit": 2})
    first = out["_meta"]["next_commands"][0]
    assert first == {
        "tool": "search_scores",
        "arguments": {"trait_id": "MONDO_0004989", "limit": 2, "offset": 2},
    }


async def test_malformed_pgs_id_names_the_pattern(facade: Any) -> None:
    res = await _raw(facade, "get_score", {"pgs_id": "PGS1"})
    body = res.structured_content
    assert res.is_error is True and body["error_code"] == "invalid_input"
    assert "must match" in body["message"] and '"PGS000001"' in body["message"]
    assert body["_meta"]["next_commands"] == [
        {"tool": "get_score", "arguments": {"pgs_id": "PGS000001"}}
    ]


async def test_performance_limit_cap_is_enforced(facade: Any) -> None:
    res = await _raw(facade, "get_score_performance", {"pgs_id": "PGS000001", "limit": 51})
    assert res.is_error is True
    assert res.structured_content["error_code"] == "invalid_input"


async def test_capabilities_and_diagnostics(facade: Any, call_tool: Any) -> None:
    caps = await call_tool(facade, "get_server_capabilities", {})
    assert caps["tools"] == TOOLS and caps["research_use_only"] is True
    diag = await call_tool(facade, "get_diagnostics", {})
    assert diag["upstream"]["base_url"] == "https://www.pgscatalog.org/rest"


async def test_get_publication_accepts_pgp_id_or_pmid(facade: Any, call_tool: Any) -> None:
    for ref in ("PGP000001", "25855707", 25855707):
        out = await call_tool(facade, "get_publication", {"publication": ref})
        assert out["publication"]["id"] == "PGP000001"


async def test_unknown_pmid_error_names_the_publication_argument(facade: Any) -> None:
    res = await _raw(facade, "get_publication", {"publication": 1})
    assert res.is_error is True
    assert res.structured_content["error_code"] == "not_found"
    assert res.structured_content["field"] == "publication"


async def test_over_cap_limit_suggests_the_clamped_call(facade: Any) -> None:
    args = {"trait_id": "MONDO_0004989", "limit": 500}
    res = await _raw(facade, "search_scores", args)
    assert res.is_error is True
    assert res.structured_content["_meta"]["next_commands"] == [
        {"tool": "search_scores", "arguments": {**args, "limit": 50}}
    ]


async def test_fix_suggestion_keeps_prefix_and_drops_unknown_or_dirty_args(facade: Any) -> None:
    res = await _raw(facade, "get_score", {"pgs_id": "PGP000001"})  # a publication ID
    assert res.structured_content["_meta"]["next_commands"] == []
    res = await _raw(facade, "get_score", {"pgs_id": "PGS18", "junk": "x\u202ey"})
    assert res.structured_content["_meta"]["next_commands"] == [
        {"tool": "get_score", "arguments": {"pgs_id": "PGS000018"}}
    ]


async def test_trait_name_in_trait_id_suggests_resolve_trait(facade: Any) -> None:
    res = await _raw(facade, "get_trait", {"trait_id": "breast cancer"})
    assert res.is_error is True
    assert res.structured_content["_meta"]["next_commands"] == [
        {"tool": "resolve_trait", "arguments": {"query": "breast cancer"}}
    ]
