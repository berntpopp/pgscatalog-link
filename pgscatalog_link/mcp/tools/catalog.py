"""Catalog tools: traits, scores, performance metrics and publications."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal, get_args

from pydantic import Field, StrictBool, StrictInt

from pgscatalog_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pgscatalog_link.mcp.envelope import McpErrorContext, ToolReturn, run_mcp_tool
from pgscatalog_link.mcp.next_commands import cmd
from pgscatalog_link.mcp.service_adapters import get_pgs_service
from pgscatalog_link.service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_PERFORMANCE_LIMIT,
    MAX_PGS_IDS,
)
from pgscatalog_link.shaping import RESPONSE_MODES

if TYPE_CHECKING:
    from fastmcp import FastMCP

PgsId = Annotated[
    str,
    Field(
        pattern=r"^[Pp][Gg][Ss]\d{6}$",
        description="PGS Catalog score ID: PGS + 6 digits.",
    ),
]
RequiredPgsId = Annotated[PgsId, Field(examples=["PGS000001"])]
TraitId = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z][A-Za-z0-9]{0,15}_[A-Za-z0-9]{1,20}$",
        description="Trait ontology ID as the catalog writes it (MONDO_0004989, "
        "EFO_0001645, HP_0000822). Get it from resolve_trait; old EFO IDs migrated to "
        "MONDO are not_found.",
    ),
]
PublicationId = Annotated[
    str,
    Field(
        pattern=r"^[Pp][Gg][Pp]\d{6}$",
        description="PGS Catalog publication ID: PGP + 6 digits.",
    ),
]
Pmid = Annotated[StrictInt, Field(ge=1, description="PubMed ID of the publication.")]
Offset = Annotated[
    StrictInt, Field(ge=0, description="Rows to skip; use the previous `next_offset`.")
]


Limit = Annotated[
    StrictInt,
    Field(ge=1, le=MAX_LIMIT, description=f"Max rows (default {DEFAULT_LIMIT}, max {MAX_LIMIT})."),
]
PerfLimit = Annotated[
    StrictInt,
    Field(
        ge=1,
        le=MAX_PERFORMANCE_LIMIT,
        description=f"Max rows (default {DEFAULT_LIMIT}, max {MAX_PERFORMANCE_LIMIT}).",
    ),
]


ResponseModeValue = Literal["minimal", "compact", "standard", "full"]
assert get_args(ResponseModeValue) == RESPONSE_MODES


def _paged(payload: dict[str, Any], tool: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    """Next page first when truncated."""
    if payload.get("next_offset") is not None:
        return [cmd(tool, **{**args, "offset": payload["next_offset"]})]
    return []


async def _run(
    tool: str,
    args: dict[str, Any],
    fetch: Callable[[], Awaitable[dict[str, Any]]],
    steps: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> ToolReturn:
    async def call() -> dict[str, Any]:
        payload = await fetch()
        payload["_meta"] = {"next_commands": steps(payload)}
        return payload

    return await run_mcp_tool(tool, call, context=McpErrorContext(tool, arguments=args))


def register_catalog_tools(mcp: FastMCP) -> None:
    """Register the catalog tools on a FastMCP instance."""

    @mcp.tool(
        name="resolve_trait",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"traits"},
        description=(
            "Find PGS Catalog traits by name, synonym or current ontology ID (EFO/MONDO/HP) "
            "and return each trait's id (the trait_id other tools take) with its categories, "
            "match (label, synonym or partial; a hint flags several exact matches), "
            "score_count (scores mapped directly) and score_count_with_descendants (direct + descendant traits; what "
            "search_scores(include_children=true) returns). Start here: other tools need "
            "the catalog's trait_id. Retired IDs are not mapped: search by name. No label or "
            "synonym match is not_found, with partial hits as candidates (match: weak). "
            "Signature: resolve_trait(query, limit=, offset=)."
        ),
    )
    async def resolve_trait(
        query: Annotated[
            str,
            Field(
                min_length=2,
                max_length=200,
                description="Trait name, synonym or ontology ID, e.g. 'type 2 diabetes'.",
                examples=["breast carcinoma"],
            ),
        ],
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> ToolReturn:
        args = {"query": query, "limit": limit, "offset": offset}

        def steps(p: dict[str, Any]) -> list[dict[str, Any]]:
            first = [cmd("search_scores", trait_id=t["id"]) for t in p["traits"][:1]]
            return first + _paged(p, "resolve_trait", args)

        return await _run(
            "resolve_trait",
            args,
            lambda: get_pgs_service().resolve_trait(query, limit, offset),
            steps,
        )

    @mcp.tool(
        name="get_trait",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"traits"},
        description=(
            "Return one trait: label, synonyms, categories, description, score counts and "
            "the first 50 PGS IDs mapped to it (pgs_ids_truncated says if there are more: "
            "page them with search_scores(trait_id)); include_children adds descendant "
            "traits and their score IDs. An unknown or retired ID is not_found. "
            "Signature: get_trait(trait_id, include_children=)."
        ),
    )
    async def get_trait(
        trait_id: Annotated[TraitId, Field(examples=["MONDO_0004989"])],
        include_children: Annotated[
            StrictBool, Field(description="Also list descendant traits and their scores.")
        ] = False,
    ) -> ToolReturn:
        args = {"trait_id": trait_id, "include_children": include_children}
        return await _run(
            "get_trait",
            args,
            lambda: get_pgs_service().get_trait(trait_id, include_children),
            lambda p: [cmd("search_scores", trait_id=p["trait"]["id"])],
        )

    @mcp.tool(
        name="search_scores",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"scores"},
        description=(
            "List polygenic scores matching ALL given selectors: trait_id (+include_children), "
            "publication_id or pmid, pgs_ids; none lists the whole catalog. Rows are in PGS "
            "ID order (pgs_ids alone keeps your order). Each row: trait, method, variant "
            "count, genome build, ancestry % per stage (gwas/dev/eval; codes in "
            "get_server_capabilities.ancestry_legend; no `dev` = no separate development "
            "sample reported) and source publication. Rows under the catalog's standard terms "
            "omit `license` (stated once as license_default); any other licence is shown "
            "on its row verbatim. `total` is exact; page with offset. "
            "Signature: search_scores(trait_id=, include_children=, publication_id=, "
            "pmid=, pgs_ids=, response_mode=, limit=, offset=)."
        ),
    )
    async def search_scores(
        trait_id: Annotated[
            TraitId | None, Field(description="Scores mapped to this trait (from resolve_trait).")
        ] = None,
        include_children: Annotated[
            StrictBool, Field(description="With trait_id: also scores of descendant traits.")
        ] = False,
        publication_id: Annotated[
            PublicationId | None,
            Field(description="Scores developed or evaluated in this PGP publication."),
        ] = None,
        pmid: Annotated[
            Pmid | None, Field(description="Scores developed or evaluated in this PubMed paper.")
        ] = None,
        pgs_ids: Annotated[
            list[PgsId] | None,
            Field(
                min_length=1,
                max_length=MAX_PGS_IDS,
                description=f"Explicit PGS IDs to summarise (1-{MAX_PGS_IDS}).",
                examples=[["PGS000001", "PGS000002"]],
            ),
        ] = None,
        response_mode: Annotated[
            ResponseModeValue,
            Field(
                description="minimal: id and name | compact (default): + trait_reported, "
                "method, variant count, build, ancestry %, publication | standard/full: + "
                "mapped traits, weight type, release date, URL and ancestry sample counts."
            ),
        ] = "compact",
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> ToolReturn:
        args = {
            k: v
            for k, v in {
                "trait_id": trait_id,
                "response_mode": None if response_mode == "compact" else response_mode,
                "include_children": include_children or None,
                "publication_id": publication_id,
                "pmid": pmid,
                "pgs_ids": pgs_ids,
                "limit": limit,
                "offset": offset,
            }.items()
            if v is not None
        }

        def steps(p: dict[str, Any]) -> list[dict[str, Any]]:
            first = [cmd("get_score", pgs_id=s["id"]) for s in p["scores"][:1]]
            return _paged(p, "search_scores", args) + first

        return await _run(
            "search_scores",
            args,
            lambda: get_pgs_service().search_scores(
                trait_id=trait_id,
                include_children=include_children,
                publication_id=publication_id,
                pmid=pmid,
                pgs_ids=pgs_ids,
                limit=limit,
                offset=offset,
                response_mode=response_mode,
            ),
            steps,
        )

    @mcp.tool(
        name="get_score",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"scores"},
        description=(
            "Return full metadata of one polygenic score: traits, method and parameters, "
            "variant count and genome build, GWAS/training samples with ancestry, the "
            "author-set licence, source publication, and download links for the original "
            "and harmonized (GRCh37/GRCh38) scoring files. variants_number counts the "
            "original file; harmonized files may map fewer. Weights are not inlined, and "
            "this server does not compute scores (use the files with the catalog's "
            "pgsc_calc). "
            "Signature: get_score(pgs_id)."
        ),
    )
    async def get_score(pgs_id: RequiredPgsId) -> ToolReturn:
        return await _run(
            "get_score",
            {"pgs_id": pgs_id},
            lambda: get_pgs_service().get_score(pgs_id),
            lambda p: [cmd("get_score_performance", pgs_id=p["score"]["id"])],
        )

    @mcp.tool(
        name="get_score_performance",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"scores"},
        description=(
            "Return the published performance metrics of one score: effect sizes (OR/HR/"
            "beta), classification accuracy (AUROC, C-index) and other metrics, each with "
            "its evaluation sample set (size, cases/controls, ancestry, cohorts) and "
            "covariates, in PPM ID order. publication_id keeps "
            "only the records from one paper (e.g. the score's source publication from "
            "get_score). The default response_mode=compact gives metrics with short names "
            "and lists each evaluation sample set once (samplesets, keyed by the row's "
            "sampleset ID); standard/full add the samples inline and the fenced prose. "
            "limit=1 just reads `total`. A score with no "
            "published metrics returns total 0; an unknown score or publication is "
            "not_found. Signature: get_score_performance(pgs_id, publication_id=, response_mode=, "
            "limit=, offset=)."
        ),
    )
    async def get_score_performance(
        pgs_id: RequiredPgsId,
        publication_id: Annotated[
            PublicationId | None,
            Field(description="Only records from this PGP publication."),
        ] = None,
        response_mode: Annotated[
            ResponseModeValue,
            Field(
                description="minimal: record and sampleset IDs with metrics | compact "
                "(default): + publication and a page-level samplesets table | standard/full: "
                "samples inline (with country) and the fenced phenotype/covariates/comments."
            ),
        ] = "compact",
        limit: PerfLimit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> ToolReturn:
        args = {
            k: v
            for k, v in {
                "pgs_id": pgs_id,
                "publication_id": publication_id,
                "response_mode": None if response_mode == "compact" else response_mode,
                "limit": limit,
                "offset": offset,
            }.items()
            if v is not None
        }
        return await _run(
            "get_score_performance",
            args,
            lambda: get_pgs_service().get_score_performance(
                pgs_id, limit, offset, publication_id, response_mode
            ),
            lambda p: (
                _paged(p, "get_score_performance", args) or [cmd("get_score", pgs_id=p["pgs_id"])]
            ),
        )

    @mcp.tool(
        name="get_publication",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"publications"},
        description=(
            "Return one PGS Catalog publication by PGP ID or PubMed ID: citation, "
            "title, and the PGS IDs it developed and evaluated. A paper the catalog does "
            "not index is not_found. Signature: get_publication(publication)."
        ),
    )
    async def get_publication(
        publication: Annotated[
            Annotated[str, Field(pattern=r"^([Pp][Gg][Pp]\d{6}|[1-9]\d{0,8})$")]
            | Annotated[StrictInt, Field(ge=1, le=999_999_999)],
            Field(
                description="PGP publication ID (PGP000001) or a PubMed ID, as a number "
                "or a string (25855707).",
                examples=["PGP000001"],
            ),
        ],
    ) -> ToolReturn:
        args = {"publication": publication}
        ref = str(publication)
        publication_id, pmid = (None, int(ref)) if ref.isdigit() else (ref, None)
        return await _run(
            "get_publication",
            args,
            lambda: get_pgs_service().get_publication(publication_id, pmid, "publication"),
            lambda p: [cmd("search_scores", publication_id=p["publication"]["id"])],
        )
