"""Live PGS Catalog REST checks (opt-in: PGSCATALOG_LINK_LIVE_INTEGRATION=1 make test-integration).

A handful of calls through the real rate limiter. Verifies the recorded-fixture assumptions
still hold upstream: a known score's variant count, the EFO->MONDO trait migration (an
obsolete EFO ID answers empty, hence not_found), and score search by trait.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from pgscatalog_link.api.client import PgsClient
from pgscatalog_link.config import PgsSettings
from pgscatalog_link.exceptions import NotFoundError
from pgscatalog_link.service import PgsService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PGSCATALOG_LINK_LIVE_INTEGRATION") != "1",
        reason="set PGSCATALOG_LINK_LIVE_INTEGRATION=1 to call the live PGS Catalog API",
    ),
]


@pytest.fixture
async def service() -> AsyncIterator[PgsService]:
    client = PgsClient(PgsSettings())
    try:
        yield PgsService(client)
    finally:
        await client.aclose()


async def test_live_get_score(service: PgsService) -> None:
    score = (await service.get_score("PGS000001"))["score"]
    assert score["id"] == "PGS000001" and score["variants_number"] == 77


async def test_live_resolve_trait_breast_carcinoma(service: PgsService) -> None:
    hits = await service.resolve_trait("breast carcinoma", 10, 0)
    assert "MONDO_0004989" in {t["id"] for t in hits["traits"]}


async def test_live_obsolete_efo_trait_is_not_found(service: PgsService) -> None:
    with pytest.raises(NotFoundError) as info:
        await service.get_trait("EFO_0000305", False)
    assert info.value.extra["field"] == "trait_id"


async def test_live_search_scores_by_trait(service: PgsService) -> None:
    page = await service.search_scores(trait_id="MONDO_0004989", limit=5)
    assert page["total"] >= 100 and page["scores"]
