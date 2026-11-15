"""Shared fixtures: a real PgsService over a respx-mocked PGS Catalog REST API.

Unit tests are network-free. ``mocked_pgs`` serves the recorded fixtures in
``tests/fixtures/pgs/`` (captured from https://www.pgscatalog.org/rest on 2026-11-15);
``facade`` wires the service into a real FastMCP instance and ``call_tool`` drives it
through an in-memory ``fastmcp.Client``.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
import respx

from pgscatalog_link.api.client import PgsClient
from pgscatalog_link.config import PgsSettings
from pgscatalog_link.mcp import metrics
from pgscatalog_link.mcp.facade import create_pgs_mcp
from pgscatalog_link.mcp.service_adapters import set_pgs_service
from pgscatalog_link.service import PgsService

FX = pathlib.Path(__file__).parent / "fixtures" / "pgs"
BASE = "https://www.pgscatalog.org/rest"


def load(name: str) -> Any:
    """Load a recorded PGS Catalog JSON fixture by file stem."""
    return json.loads((FX / f"{name}.json").read_text())


def fast_settings() -> PgsSettings:
    """Upstream settings with politeness spacing disabled so tests run instantly."""
    return PgsSettings(min_interval_s=0.0, backoff_base_s=0.0)


def _ok(name: str) -> httpx.Response:
    return httpx.Response(200, json=load(name))


def _score_search(request: httpx.Request) -> httpx.Response:
    wanted = set(request.url.params.get("pgs_ids", "").split(","))
    page = load("score_search_ids")
    rows = [r for r in page["results"] if r["id"] in wanted]
    return httpx.Response(
        200, json={**page, "size": len(rows), "count": len(rows), "results": rows}
    )


def _performance(request: httpx.Request) -> httpx.Response:
    if request.url.params.get("pgs_id") == "PGS000001":
        page = load("performance_PGS000001")
        pgp = request.url.params.get("pgp_id")
        if pgp is None:
            return httpx.Response(200, json=page)
        rows = [r for r in page["results"] if r["publication"]["id"] == pgp]
        return httpx.Response(200, json={**page, "count": len(rows), "results": rows})
    return httpx.Response(
        200, json={"size": 0, "count": 0, "next": None, "previous": None, "results": []}
    )


def _trait_search(request: httpx.Request) -> httpx.Response:
    hit = "diabetes" in request.url.params.get("term", "")
    return _ok("trait_search_diabetes" if hit else "trait_search_empty")


def _publication_search(request: httpx.Request) -> httpx.Response:
    if request.url.params.get("pmid") == "25855707":
        return _ok("publication_search_pmid")
    return _ok("trait_search_empty")  # same empty-page shape


@pytest.fixture(autouse=True)
def _reset_metrics() -> Iterator[None]:
    """Keep the process-wide metrics collector clean between tests."""
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture
def mocked_pgs() -> Iterator[respx.MockRouter]:
    """A respx router serving the recorded PGS Catalog fixtures."""
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.get("/info").mock(return_value=_ok("info"))
        router.get("/score/PGS000001").mock(return_value=_ok("score_PGS000001"))
        router.get("/score/PGS000002").mock(return_value=_ok("score_PGS000001"))
        router.get("/score/PGS999999").mock(return_value=_ok("score_unknown"))
        router.get("/score/search").mock(side_effect=_score_search)
        router.get("/score/all").mock(return_value=_ok("score_all"))
        router.get("/trait/MONDO_0004989").mock(return_value=_ok("trait_MONDO_0004989"))
        router.get("/trait/EFO_0000305").mock(return_value=_ok("trait_unknown"))
        router.get("/trait/search").mock(side_effect=_trait_search)
        router.get("/performance/search").mock(side_effect=_performance)
        router.get("/publication/PGP000001").mock(return_value=_ok("publication_PGP000001"))
        router.get("/publication/PGP999999").mock(return_value=_ok("publication_unknown"))
        router.get("/publication/search").mock(side_effect=_publication_search)
        yield router


@pytest.fixture
async def pgs_service(mocked_pgs: respx.MockRouter) -> AsyncIterator[PgsService]:
    """A real PgsService over the respx-mocked client."""
    client = PgsClient(fast_settings())
    try:
        yield PgsService(client)
    finally:
        await client.aclose()


@pytest.fixture
def facade(pgs_service: PgsService) -> Iterator[Any]:
    """A FastMCP facade with the fixture service injected; cleans up after."""
    mcp = create_pgs_mcp(service_factory=lambda: pgs_service)
    yield mcp
    set_pgs_service(None)


@pytest.fixture
def call_tool() -> Callable[[Any, str, dict[str, Any]], Awaitable[Any]]:
    """Call a tool through an in-memory ``fastmcp.Client``; return the structured dict."""
    from fastmcp import Client

    async def _call(mcp: Any, name: str, args: dict[str, Any]) -> Any:
        async with Client(mcp) as client:
            res = await client.call_tool(name, args, raise_on_error=False)
        if isinstance(res.structured_content, dict):
            return res.structured_content
        return res.data

    return _call
