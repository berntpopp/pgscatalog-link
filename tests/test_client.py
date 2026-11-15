"""PGS Catalog REST client: honest User-Agent, caching, backoff and typed errors."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from pgscatalog_link import __version__
from pgscatalog_link.api.client import PgsClient
from pgscatalog_link.exceptions import (
    InvalidInputError,
    RateLimitedError,
    UpstreamSchemaError,
    UpstreamUnavailableError,
)
from tests.conftest import BASE, fast_settings, load

PATH = "/score/PGS000001"
PARAMS: dict[str, object] = {}


@pytest.fixture
async def client() -> AsyncIterator[PgsClient]:
    c = PgsClient(fast_settings())
    yield c
    await c.aclose()


@respx.mock(base_url=BASE)
async def test_sends_honest_user_agent_and_returns_json(
    respx_mock: respx.MockRouter, client: PgsClient
) -> None:
    route = respx_mock.get(PATH).mock(
        return_value=httpx.Response(200, json=load("score_PGS000001"))
    )
    data = await client.get_json(PATH, PARAMS)
    assert data["id"] == "PGS000001"
    ua = route.calls.last.request.headers["user-agent"]
    assert (
        ua.startswith(f"pgscatalog-link/{__version__}")
        and "github.com/berntpopp/pgscatalog-link" in ua
    )


@respx.mock(base_url=BASE)
async def test_partial_206_is_a_success(respx_mock: respx.MockRouter, client: PgsClient) -> None:
    respx_mock.get(PATH).mock(return_value=httpx.Response(206, json=load("score_PGS000001")))
    data = await client.get_json(PATH, PARAMS)
    assert data["id"] == "PGS000001"


@respx.mock(base_url=BASE)
async def test_identical_calls_hit_upstream_once(
    respx_mock: respx.MockRouter, client: PgsClient
) -> None:
    route = respx_mock.get(PATH).mock(
        return_value=httpx.Response(200, json=load("score_PGS000001"))
    )
    await client.get_json(PATH, PARAMS)
    await client.get_json(PATH, dict(PARAMS))
    assert route.call_count == 1


@respx.mock(base_url=BASE)
async def test_limit_400_is_invalid_input_naming_limit(
    respx_mock: respx.MockRouter, client: PgsClient
) -> None:
    respx_mock.get("/score/search").mock(return_value=httpx.Response(400, json=load("limit_400")))
    with pytest.raises(InvalidInputError) as info:
        await client.get_json("/score/search", {"trait_id": "MONDO_0004989", "limit": 251})
    assert info.value.extra["field"] == "limit"
    assert "250" not in info.value.message  # upstream body is never echoed


@respx.mock(base_url=BASE)
async def test_other_400_is_invalid_input_with_fixed_message(
    respx_mock: respx.MockRouter, client: PgsClient
) -> None:
    respx_mock.get("/score/search").mock(
        return_value=httpx.Response(400, json={"status_code": 400, "message": "bad PGS999"})
    )
    with pytest.raises(InvalidInputError) as info:
        await client.get_json("/score/search", {"pgs_ids": "x"})
    assert "PGS999" not in info.value.message
    assert "field" not in info.value.extra


@respx.mock(base_url=BASE)
async def test_429_retries_then_rate_limited_with_retry_after(
    respx_mock: respx.MockRouter, client: PgsClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("pgscatalog_link.api.client.asyncio.sleep", _sleep)
    route = respx_mock.get(PATH).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "7"})
    )
    with pytest.raises(RateLimitedError) as info:
        await client.get_json(PATH, PARAMS)
    assert route.call_count == 1 + fast_settings().max_retries
    assert info.value.extra["retry_after_s"] == 7.0
    assert slept == [7.0, 7.0]  # backoff honours Retry-After


@respx.mock(base_url=BASE)
async def test_503_then_success_recovers(respx_mock: respx.MockRouter, client: PgsClient) -> None:
    respx_mock.get(PATH).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=load("score_PGS000001"))]
    )
    data = await client.get_json(PATH, PARAMS)
    assert data["id"] == "PGS000001"


@respx.mock(base_url=BASE)
async def test_persistent_timeout_is_retryable_upstream_unavailable(
    respx_mock: respx.MockRouter, client: PgsClient
) -> None:
    respx_mock.get(PATH).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamUnavailableError) as info:
        await client.get_json(PATH, PARAMS)
    assert info.value.retryable is True


@respx.mock(base_url=BASE)
async def test_non_json_success_is_schema_error(
    respx_mock: respx.MockRouter, client: PgsClient
) -> None:
    respx_mock.get(PATH).mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(UpstreamSchemaError):
        await client.get_json(PATH, PARAMS)


async def test_rate_limit_refusal_propagates_before_any_request() -> None:
    settings = fast_settings()
    settings.daily_cap = 1
    c = PgsClient(settings)
    with respx.mock(base_url=BASE) as router:
        route = router.get(PATH).mock(
            return_value=httpx.Response(200, json=load("score_PGS000001"))
        )
        await c.get_json(PATH, PARAMS)
        with pytest.raises(RateLimitedError):
            await c.get_json(PATH, {"x": 1})
        assert route.call_count == 1
    await c.aclose()


@respx.mock(base_url=BASE)
async def test_concurrent_identical_calls_share_one_upstream_request(
    respx_mock: respx.MockRouter, client: PgsClient
) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)  # let the other callers start while this one is in flight
        return httpx.Response(200, json=load("score_PGS000001"))

    route = respx_mock.get(PATH).mock(side_effect=slow)
    results = await asyncio.gather(*(client.get_json(PATH, PARAMS) for _ in range(3)))
    assert route.call_count == 1
    assert all(r["id"] == "PGS000001" for r in results)
