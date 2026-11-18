"""The 2026-07-28 sessionless protocol era works end-to-end over HTTP.

Drives ``server/discover`` -> ``tools/list`` -> ``tools/call`` (known + unknown tool)
through the same FastAPI app + MCP ASGI app assembly the unified server deploys, so
the CORS / Host-Origin guards accept the modern ``mcp-method`` / ``mcp-name`` headers
and the not-found guard still fences a caller-supplied tool name.
"""

from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from pgscatalog_link.app import create_app
from pgscatalog_link.config import settings
from pgscatalog_link.mcp.facade import create_pgs_mcp

_MODERN_VERSION = "2026-07-28"
_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": _MODERN_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "pgscatalog-host-test", "version": "1.0.0"},
}


def _headers(method: str, *, name: str | None = None) -> dict[str, str]:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "host": "localhost",
        "mcp-protocol-version": _MODERN_VERSION,
        "mcp-method": method,
    }
    if name is not None:
        headers["mcp-name"] = name
    return headers


def _client() -> TestClient:
    mcp_asgi = create_pgs_mcp().http_app(
        path=settings.mcp_path,
        stateless_http=True,
        json_response=True,
        host_origin_protection=True,
        allowed_hosts=["localhost"],
        allowed_origins=[],
    )
    app = create_app()
    app.router.lifespan_context = mcp_asgi.router.lifespan_context
    app.mount("/", mcp_asgi)
    return TestClient(app, follow_redirects=False)


def _post(
    client: TestClient, rid: int, method: str, params: dict[str, object], name: str | None = None
) -> httpx.Response:
    return client.post(
        settings.mcp_path,
        headers=_headers(method, name=name),
        json={
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": {"_meta": _MODERN_META, **params},
        },
    )


def test_modern_mcp_http_discovers_lists_calls_and_fences_unknown_tool() -> None:
    hostile = "ignore-instructions-secret"
    with _client() as client:
        discover = _post(client, 1, "server/discover", {})
        listed = _post(client, 2, "tools/list", {})
        called = _post(
            client,
            3,
            "tools/call",
            {"name": "get_server_capabilities", "arguments": {}},
            name="get_server_capabilities",
        )
        unknown = _post(client, 4, "tools/call", {"name": hostile, "arguments": {}}, name=hostile)

    assert discover.status_code == 200, discover.text
    assert _MODERN_VERSION in discover.json()["result"]["supportedVersions"]
    assert "mcp-session-id" not in discover.headers
    assert listed.status_code == 200
    assert "get_server_capabilities" in {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert called.status_code == 200
    called_result = called.json()["result"]
    assert json.loads(called_result["content"][0]["text"]) == called_result["structuredContent"]
    assert called_result["structuredContent"]["success"] is True
    assert unknown.status_code == 200
    unknown_result = unknown.json()["result"]
    assert unknown_result["isError"] is True
    assert unknown_result["structuredContent"]["error_code"] == "not_found"
    assert hostile not in unknown.text
