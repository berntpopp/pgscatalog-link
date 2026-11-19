"""Data-plane behaviour over recorded PGS Catalog responses (network-free)."""

from __future__ import annotations

from typing import Any

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
    assert {"id", "label", "score_count", "score_count_with_descendants"} <= set(out["traits"][0])


async def test_resolve_trait_miss_is_not_found_with_next_commands(pgs_service: PgsService) -> None:
    with pytest.raises(NotFoundError) as err:
        await pgs_service.resolve_trait("zzqqxx", 3, 0)
    extra = err.value.extra
    assert extra["field"] == "query" and extra["candidates"] == [] and "broader" in extra["hint"]
    assert extra["next_commands"] == [
        {"tool": "mondo_resolve_disease", "arguments": {"query": "zzqqxx"}}
    ]
    assert "zzqqxx" not in err.value.message  # never echo the query into the message


async def test_resolve_trait_partial_only_is_not_found_with_weak_candidates(
    pgs_service: PgsService, mocked_pgs: respx.MockRouter
) -> None:
    page = load("trait_search_diabetes")
    partial = [r for r in page["results"] if r["id"] != "MONDO_0005015"][:2]
    mocked_pgs.get("/trait/search").mock(
        return_value=httpx.Response(200, json={**page, "count": 2, "results": partial})
    )
    with pytest.raises(NotFoundError) as err:
        await pgs_service.resolve_trait("diabetes", 3, 0)
    cands = err.value.extra["candidates"]
    assert [c["id"] for c in cands] == [r["id"] for r in partial]
    assert {c["match"] for c in cands} == {"weak"}
    assert [c["tool"] for c in err.value.extra["next_commands"]] == [
        "search_scores",
        "mondo_resolve_disease",
    ]
    assert err.value.extra["next_commands"][0]["arguments"] == {"trait_id": partial[0]["id"]}


async def test_resolve_trait_truncated_page_without_exact_stays_success(
    pgs_service: PgsService, mocked_pgs: respx.MockRouter
) -> None:
    # an exact match may sit on a later page: a partial-only page is not a miss
    page = load("trait_search_diabetes")
    partial = [r for r in page["results"] if r["id"] != "MONDO_0005015"][:2]
    mocked_pgs.get("/trait/search").mock(
        return_value=httpx.Response(200, json={**page, "results": partial})
    )
    out = await pgs_service.resolve_trait("diabetes", 2, 0)
    assert out["truncated"] is True and {t["match"] for t in out["traits"]} == {"partial"}


async def test_obsolete_trait_id_is_not_found_naming_the_field(pgs_service: PgsService) -> None:
    with pytest.raises(NotFoundError) as err:
        await pgs_service.get_trait("EFO_0000305", False)
    assert err.value.extra["field"] == "trait_id" and "resolve_trait" in str(err.value.extra)


async def test_get_trait_children_are_opt_in(pgs_service: PgsService) -> None:
    plain = (await pgs_service.get_trait("MONDO_0004989", False))["trait"]
    assert "descendant_pgs_ids" not in plain and plain["score_count"] == 145
    assert len(plain["pgs_ids"]) == 50 and plain["pgs_ids_truncated"] is True
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
    assert out["total"] == 1  # counts existing scores, not requested IDs
    assert out["license_default"].startswith("PGS obtained from the Catalog")
    assert "license" not in out["scores"][0]  # standard terms are stated once


async def test_search_scores_all_unknown_ids_is_not_found(pgs_service: PgsService) -> None:
    with pytest.raises(NotFoundError):
        await pgs_service.search_scores(pgs_ids=["PGS999999"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"pmid": 25855707, "include_children": True},
        {"include_children": True},
        {"publication_id": "PGP000001", "pmid": 25855707},
    ],
)
async def test_search_scores_rejects_meaningless_selector_mixes(
    pgs_service: PgsService, kwargs: dict[str, object]
) -> None:
    with pytest.raises(InvalidInputError):
        await pgs_service.search_scores(**kwargs)  # type: ignore[arg-type]


async def test_search_scores_selectors_combine_with_and(pgs_service: PgsService) -> None:
    trait = set(load("trait_MONDO_0004989")["associated_pgs_ids"])
    out = await pgs_service.search_scores(trait_id="MONDO_0004989", pmid=25855707)
    expected = sorted(trait & {"PGS000001", "PGS000002", "PGS000003"})
    assert out["selector"] == {
        "trait_id": "MONDO_0004989",
        "include_children": False,
        "publication_id": "PGP000001",
        "pmid": 25855707,
        "matches_per_selector": [len(trait), 3],
    }
    assert out["total"] == len(expected) and [s["id"] for s in out["scores"]] == expected
    with pytest.raises(NotFoundError):  # each selector is still validated
        await pgs_service.search_scores(trait_id="MONDO_0004989", pmid=1)
    mixed = await pgs_service.search_scores(
        trait_id="MONDO_0004989", pgs_ids=["PGS000001", "PGS999999"]
    )
    assert [s["id"] for s in mixed["scores"]] == ["PGS000001"]
    assert mixed["missing_pgs_ids"] == ["PGS999999"]  # never silently dropped
    with pytest.raises(NotFoundError):
        await pgs_service.search_scores(trait_id="MONDO_0004989", pgs_ids=["PGS999999"])


async def test_search_scores_by_publication_unions_dev_and_eval(pgs_service: PgsService) -> None:
    out = await pgs_service.search_scores(pmid=25855707)
    assert out["selector"] == {"publication_id": "PGP000001", "pmid": 25855707}
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
    out = await pgs_service.get_score_performance("PGS000001", 2, 0, response_mode="full")
    assert out["total"] == load("performance_PGS000001")["count"]
    row = out["performance"][0]
    assert row["effect_sizes"][0]["name_short"] == "OR" and row["sampleset"]["samples"]
    with pytest.raises(NotFoundError):
        await pgs_service.get_score_performance("PGS999999", 2, 0)


async def test_performance_filtered_by_publication(pgs_service: PgsService) -> None:
    rows = load("performance_PGS000001")["results"]
    own = [r["id"] for r in rows if r["publication"]["id"] == "PGP000001"]
    out = await pgs_service.get_score_performance("PGS000001", 25, 0, "pgp000001")
    assert out["publication_id"] == "PGP000001" and out["total"] == len(own) > 0
    assert [r["id"] for r in out["performance"]] == own
    with pytest.raises(NotFoundError) as err:  # an unknown filter is never a silent empty list
        await pgs_service.get_score_performance("PGS000001", 25, 0, "PGP999999")
    assert err.value.extra["field"] == "publication_id"


async def test_ontology_id_without_hit_explains_retired_ids(pgs_service: PgsService) -> None:
    with pytest.raises(NotFoundError) as err:
        await pgs_service.resolve_trait("EFO_0000305", 3, 0)
    assert "retired" in err.value.extra["hint"]
    assert "next_commands" not in err.value.extra  # an ID is not disease text


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


def test_only_the_standard_license_is_factored_out() -> None:
    from pgscatalog_link.shaping import STANDARD_LICENSE, factor_license

    rows = [{"license": "a"}, {"license": "a"}]
    assert factor_license(rows) is None and rows == [{"license": "a"}, {"license": "a"}]
    rows = [{"license": STANDARD_LICENSE}, {"license": "CC BY 4.0"}]
    assert factor_license(rows) == STANDARD_LICENSE and rows == [{}, {"license": "CC BY 4.0"}]


async def test_performance_response_modes_are_projections(pgs_service: PgsService) -> None:
    def call(mode: str) -> Any:
        return pgs_service.get_score_performance("PGS000001", 50, 0, response_mode=mode)

    full, compact, minimal = await call("full"), await call("compact"), await call("minimal")
    assert full["total"] == compact["total"] == minimal["total"]  # B3: never destroy
    assert [r["id"] for r in full["performance"]] == [r["id"] for r in minimal["performance"]]
    row, wide = compact["performance"][0], full["performance"][0]
    assert wide["reported"]["kind"] == "untrusted_text" and "reported" not in row
    assert all("name_long" not in m for m in row["classification_metrics"])
    samples = compact["samplesets"][row["sampleset"]]
    assert samples and all("ancestry_country" not in s for s in samples)
    assert "publication" not in minimal["performance"][0] and "samplesets" not in minimal
    with pytest.raises(InvalidInputError):
        await pgs_service.get_score_performance("PGS000001", 51, 0)


async def test_score_lists_cohorts_once(pgs_service: PgsService) -> None:
    score = (await pgs_service.get_score("PGS000001"))["score"]
    assert all("cohorts" not in s for s in score["samples_variants"])
    assert score["cohort_count"] == len(score["cohorts"])


def test_authors_are_capped_with_a_count() -> None:
    from pgscatalog_link.shaping import publication_detail

    out = publication_detail(
        {"id": "PGP000001", "authors": ", ".join(f"A{i} X" for i in range(30))}
    )
    assert out["author_count"] == 30 and out["authors"].endswith("A9 X, et al.")


def test_trait_match_kind() -> None:
    from pgscatalog_link.shaping import match_kind

    raw = {"id": "MONDO_0004989", "label": "breast carcinoma", "trait_synonyms": ["breast cancer"]}
    assert [match_kind(raw, q) for q in ("Breast Carcinoma", "breast cancer", "breast")] == [
        "label",
        "synonym",
        "partial",
    ]


async def test_score_response_modes_are_projections(pgs_service: PgsService) -> None:
    def call(mode: str) -> Any:
        return pgs_service.search_scores(trait_id="MONDO_0004989", limit=2, response_mode=mode)

    minimal, compact, full = await call("minimal"), await call("compact"), await call("full")
    assert minimal["total"] == compact["total"] == full["total"] == 145
    assert set(minimal["scores"][0]) == {"id", "name"}
    assert "traits" not in compact["scores"][0] and "traits" in full["scores"][0]
    assert compact["scores"][0]["ancestry_distribution"] == {
        k: v["dist"] for k, v in full["scores"][0]["ancestry_distribution"].items()
    }
