"""Data-plane behaviour over recorded PGS Catalog responses (network-free)."""

from __future__ import annotations

import httpx
import pytest
import respx

from pgscatalog_link.exceptions import InvalidInputError, NotFoundError
from pgscatalog_link.service import PgsService
from tests.conftest import load


async def test_resolve_trait_pages_with_exact_total(pgs_service: PgsService) -> None:
    out = await pgs_service.resolve_trait("diabetes", 3, 0)
    upstream = load("trait_search_diabetes")
    assert out["total"] == upstream["count"] and out["returned"] == 3
    assert out["truncated"] is (upstream["count"] > 3) and out["next_offset"] == 3
    assert out["data_version"] == "PGS Catalog release 2026-10-23"
    assert {"id", "label", "score_count", "descendant_score_count"} <= set(out["traits"][0])


async def test_resolve_trait_without_hits_is_honest_empty(pgs_service: PgsService) -> None:
    out = await pgs_service.resolve_trait("zzqqxx", 3, 0)
    assert out["total"] == 0 and out["traits"] == [] and out["truncated"] is False


async def test_obsolete_trait_id_is_not_found_naming_the_field(pgs_service: PgsService) -> None:
    with pytest.raises(NotFoundError) as err:
        await pgs_service.get_trait("EFO_0000305", False)
    assert err.value.extra["field"] == "trait_id" and "resolve_trait" in str(err.value.extra)


async def test_get_trait_children_are_opt_in(pgs_service: PgsService) -> None:
    plain = (await pgs_service.get_trait("MONDO_0004989", False))["trait"]
    assert "descendant_pgs_ids" not in plain and len(plain["pgs_ids"]) == 145
    full = (await pgs_service.get_trait("MONDO_0004989", True))["trait"]
    assert full["descendant_pgs_ids"] and not set(full["descendant_pgs_ids"]) & set(
        plain["pgs_ids"]
    )
    assert full["description"]["kind"] == "untrusted_text"


async def test_search_scores_by_trait_counts_ids_exactly(pgs_service: PgsService) -> None:
    out = await pgs_service.search_scores(trait_id="MONDO_0004989", limit=2)
    assert out["total"] == 145 and out["truncated"] is True and out["next_offset"] == 2
    children = await pgs_service.search_scores(trait_id="MONDO_0004989", include_children=True)
    assert children["total"] > out["total"]


async def test_search_scores_reports_missing_ids(pgs_service: PgsService) -> None:
    out = await pgs_service.search_scores(pgs_ids=["pgs000001", "PGS999999"])
    assert [s["id"] for s in out["scores"]] == ["PGS000001"]
    assert out["missing_pgs_ids"] == ["PGS999999"] and out["returned"] == 1
    assert out["scores"][0]["license"].startswith("PGS obtained from the Catalog")


async def test_search_scores_all_unknown_ids_is_not_found(pgs_service: PgsService) -> None:
    with pytest.raises(NotFoundError):
        await pgs_service.search_scores(pgs_ids=["PGS999999"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trait_id": "MONDO_0004989", "pmid": 1},
        {"pmid": 25855707, "include_children": True},
        {"include_children": True},
    ],
)
async def test_search_scores_takes_at_most_one_selector(
    pgs_service: PgsService, kwargs: dict[str, object]
) -> None:
    with pytest.raises(InvalidInputError):
        await pgs_service.search_scores(**kwargs)  # type: ignore[arg-type]


async def test_search_scores_by_publication_unions_dev_and_eval(pgs_service: PgsService) -> None:
    out = await pgs_service.search_scores(pmid=25855707)
    assert out["selector"] == {"publication_id": "PGP000001"}
    assert out["total"] == 3


async def test_get_score_links_files_and_keeps_licence(pgs_service: PgsService) -> None:
    score = (await pgs_service.get_score("PGS000001"))["score"]
    assert score["variants_number"] == 77
    assert score["scoring_files"]["harmonized"]["GRCh38"].endswith("_hmPOS_GRCh38.txt.gz")
    assert score["license"] == load("score_PGS000001")["license"]
    assert score["ancestry_distribution"]["gwas"]["dist"] == {"EUR": 100}


async def test_unknown_score_answering_200_empty_is_not_found(pgs_service: PgsService) -> None:
    with pytest.raises(NotFoundError) as err:
        await pgs_service.get_score("PGS999999")
    assert err.value.extra["field"] == "pgs_id"


async def test_bad_identifier_never_reaches_upstream(
    pgs_service: PgsService, mocked_pgs: respx.MockRouter
) -> None:
    with pytest.raises(InvalidInputError):
        await pgs_service.get_score("../info")
    assert not mocked_pgs.calls


async def test_performance_rows_and_unknown_score(pgs_service: PgsService) -> None:
    out = await pgs_service.get_score_performance("PGS000001", 2, 0)
    assert out["total"] == load("performance_PGS000001")["count"]
    row = out["performance"][0]
    assert row["effect_sizes"][0]["name_short"] == "OR" and row["sampleset"]["samples"]
    with pytest.raises(NotFoundError):
        await pgs_service.get_score_performance("PGS999999", 2, 0)


async def test_publication_lookup_both_ways(pgs_service: PgsService) -> None:
    by_id = (await pgs_service.get_publication(publication_id="PGP000001"))["publication"]
    by_pmid = (await pgs_service.get_publication(pmid=25855707))["publication"]
    assert by_id["id"] == by_pmid["id"] == "PGP000001"
    assert by_id["developed_pgs_ids"] == ["PGS000001", "PGS000002", "PGS000003"]
    assert by_id["title"]["kind"] == "untrusted_text"
    with pytest.raises(NotFoundError):
        await pgs_service.get_publication(pmid=1)
    with pytest.raises(NotFoundError):
        await pgs_service.get_publication(publication_id="PGP999999")


async def test_upstream_page_limit_400_is_invalid_input(
    pgs_service: PgsService, mocked_pgs: respx.MockRouter
) -> None:
    mocked_pgs.get("/trait/search").mock(return_value=httpx.Response(400, json=load("limit_400")))
    with pytest.raises(InvalidInputError) as err:
        await pgs_service.resolve_trait("diabetes", 3, 0)
    assert err.value.extra["field"] == "limit"


async def test_search_scores_without_selector_pages_the_catalog(pgs_service: PgsService) -> None:
    out = await pgs_service.search_scores(limit=2)
    assert out["selector"] == {"all": True} and out["total"] == load("score_all")["count"]
    assert [s["id"] for s in out["scores"]] == ["PGS000001", "PGS000002"]
