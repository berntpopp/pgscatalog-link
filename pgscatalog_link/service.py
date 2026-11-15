"""PGS Catalog data plane: validate identifiers, query the REST API, shape honest payloads.

Returns plain dicts and raises typed :mod:`pgscatalog_link.exceptions` errors; the MCP
envelope owns ``success``/``_meta``. The catalog answers an unknown identifier with
``200 {}`` and an unknown or obsolete trait in a search with ``count: 0``; both are
turned into ``not_found`` naming the offending argument, never a silent empty list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pgscatalog_link.api.client import PgsClient
from pgscatalog_link.exceptions import InvalidInputError, NotFoundError, UpstreamSchemaError
from pgscatalog_link.shaping import (
    PGP_ID,
    PGS_ID,
    TRAIT_ID,
    page_block,
    performance_row,
    publication_detail,
    score_detail,
    score_summary,
    trait_detail,
    trait_summary,
)

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
#: Performance rows carry up to three fenced prose fields each (128-object fence cap).
MAX_PERFORMANCE_LIMIT = 25
MAX_PGS_IDS = 50


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _check(value: str, pattern: Any, field: str, example: str) -> str:
    candidate = value.strip()
    if pattern in (PGS_ID, PGP_ID):
        candidate = candidate.upper()
    if not pattern.fullmatch(candidate):
        raise InvalidInputError(
            f"`{field}` is not a valid identifier (expected e.g. {example}).",
            field=field,
            recovery_action="reformulate_input",
        )
    return candidate


def _page_args(limit: int, offset: int, maximum: int) -> None:
    if not 1 <= limit <= maximum:
        raise InvalidInputError(f"`limit` must be 1-{maximum}.", field="limit")
    if offset < 0:
        raise InvalidInputError("`offset` must be >= 0.", field="offset")


def _results(page: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    results, count = page.get("results"), page.get("count")
    if not isinstance(results, list) or not isinstance(count, int):
        raise UpstreamSchemaError("The PGS Catalog returned an unexpected page.", field="results")
    return [r for r in results if isinstance(r, dict)], count


class PgsService:
    """All PGS Catalog queries; one instance per process over a shared client."""

    def __init__(self, client: PgsClient) -> None:
        """Bind the service to a rate-limited, cached upstream client."""
        self.client = client

    async def release(self) -> dict[str, Any]:
        """The catalog's current data release and REST API version (cached)."""
        info = await self.client.get_json("/info", {})
        latest = info.get("latest_release") or {}
        return {
            "data_release": latest.get("date"),
            "rest_api_version": (info.get("rest_api") or {}).get("version"),
            "scores": latest.get("scores"),
            "publications": latest.get("publications"),
            "traits": latest.get("traits"),
        }

    async def _stamp(self, payload: dict[str, Any]) -> dict[str, Any]:
        release = await self.release()
        payload["data_version"] = f"PGS Catalog release {release['data_release']}"
        payload["retrieved_at"] = _now()
        return payload

    async def _record(
        self, path: str, field: str, value: str, hint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        raw = await self.client.get_json(path, params or {})
        if not raw.get("id"):  # the catalog answers unknown IDs with 200 {}
            raise NotFoundError(
                f"No PGS Catalog record for `{field}` {value}.",
                field=field,
                hint=hint,
                recovery_action="reformulate_input",
            )
        return raw

    async def resolve_trait(self, query: str, limit: int, offset: int) -> dict[str, Any]:
        """Free text (or an ontology ID) -> catalog traits with their score counts."""
        _page_args(limit, offset, MAX_LIMIT)
        term = query.strip()
        if not 2 <= len(term) <= 200:
            raise InvalidInputError("`query` must be 2-200 characters.", field="query")
        page = await self.client.get_json(
            "/trait/search", {"term": term, "limit": limit, "offset": offset}
        )
        rows, count = _results(page)
        items = [trait_summary(r) for r in rows]
        return await self._stamp(
            {
                "query": term,
                "traits": items,
                **page_block(total=count, returned=len(items), limit=limit, offset=offset),
            }
        )

    async def _trait(self, trait_id: str) -> dict[str, Any]:
        tid = _check(trait_id, TRAIT_ID, "trait_id", "MONDO_0004989")
        return await self._record(
            f"/trait/{tid}",
            "trait_id",
            tid,
            "The catalog has migrated many EFO traits to MONDO; find the current ID "
            "with resolve_trait(query=<trait name>).",
            {"include_children": 1},
        )

    async def get_trait(self, trait_id: str, include_children: bool) -> dict[str, Any]:
        """One trait with the scores mapped to it (and, optionally, to its descendants)."""
        raw = await self._trait(trait_id)
        return await self._stamp({"trait": trait_detail(raw, include_children=include_children)})

    async def _ids_for(
        self,
        trait_id: str | None,
        include_children: bool,
        publication_id: str | None,
        pmid: int | None,
        pgs_ids: list[str] | None,
    ) -> tuple[dict[str, Any], list[str]]:
        given = [v is not None for v in (trait_id, publication_id, pmid, pgs_ids)]
        if sum(given) > 1:
            raise InvalidInputError(
                "Give at most one of `trait_id`, `publication_id`, `pmid` or `pgs_ids`.",
                field="trait_id",
            )
        if include_children and trait_id is None:
            raise InvalidInputError(
                "`include_children` only applies with `trait_id`.", field="include_children"
            )
        if trait_id is not None:
            raw = await self._trait(trait_id)
            ids = set(raw.get("associated_pgs_ids") or [])
            if include_children:
                ids |= set(raw.get("child_associated_pgs_ids") or [])
            selector = {"trait_id": raw["id"], "include_children": include_children}
            return selector, sorted(ids)
        if pgs_ids is not None:
            if not 1 <= len(pgs_ids) <= MAX_PGS_IDS:
                raise InvalidInputError(f"`pgs_ids` takes 1-{MAX_PGS_IDS} IDs.", field="pgs_ids")
            wanted = [_check(v, PGS_ID, "pgs_ids", "PGS000001") for v in pgs_ids]
            return {"pgs_ids": wanted}, list(dict.fromkeys(wanted))
        pub = await self._publication(publication_id, pmid)
        associated = pub.get("associated_pgs_ids") or {}
        ids = set(associated.get("development") or []) | set(associated.get("evaluation") or [])
        return {"publication_id": pub["id"]}, sorted(ids)

    async def search_scores(
        self,
        *,
        trait_id: str | None = None,
        include_children: bool = False,
        publication_id: str | None = None,
        pmid: int | None = None,
        pgs_ids: list[str] | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Scores selected by exactly one of trait, publication or an explicit ID list."""
        _page_args(limit, offset, MAX_LIMIT)
        if not any(v is not None for v in (trait_id, publication_id, pmid, pgs_ids)):
            if include_children:
                raise InvalidInputError(
                    "`include_children` only applies with `trait_id`.", field="include_children"
                )
            return await self._all_scores(limit, offset)
        selector, ids = await self._ids_for(
            trait_id, include_children, publication_id, pmid, pgs_ids
        )
        window = ids[offset : offset + limit]
        found: dict[str, dict[str, Any]] = {}
        if window:
            page = await self.client.get_json(
                "/score/search", {"pgs_ids": ",".join(window), "limit": len(window)}
            )
            found = {str(r.get("id")): r for r in _results(page)[0]}
        missing = [i for i in window if i not in found]
        if pgs_ids is not None and window and not found:
            raise NotFoundError(
                "None of the requested `pgs_ids` exist in the PGS Catalog.", field="pgs_ids"
            )
        items = [score_summary(found[i]) for i in window if i in found]
        payload = {
            "selector": selector,
            "scores": items,
            **page_block(total=len(ids), returned=len(window), limit=limit, offset=offset),
            "returned": len(items),  # paging counts IDs; missing ones are listed below
        }
        if missing:
            payload["missing_pgs_ids"] = missing
        return await self._stamp(payload)

    async def _all_scores(self, limit: int, offset: int) -> dict[str, Any]:
        """No selector: page through the whole catalog in its native (PGS ID) order."""
        page = await self.client.get_json("/score/all", {"limit": limit, "offset": offset})
        rows, count = _results(page)
        items = [score_summary(r) for r in rows]
        return await self._stamp(
            {
                "selector": {"all": True},
                "scores": items,
                **page_block(total=count, returned=len(items), limit=limit, offset=offset),
            }
        )

    async def get_score(self, pgs_id: str) -> dict[str, Any]:
        """Full metadata of one score, with links to its scoring files."""
        sid = _check(pgs_id, PGS_ID, "pgs_id", "PGS000001")
        raw = await self._record(
            f"/score/{sid}", "pgs_id", sid, "Find scores with search_scores(trait_id=...)."
        )
        return await self._stamp({"score": score_detail(raw)})

    async def get_score_performance(self, pgs_id: str, limit: int, offset: int) -> dict[str, Any]:
        """Published performance metrics (PPM) of one score, with evaluation samples."""
        _page_args(limit, offset, MAX_PERFORMANCE_LIMIT)
        sid = _check(pgs_id, PGS_ID, "pgs_id", "PGS000001")
        page = await self.client.get_json(
            "/performance/search", {"pgs_id": sid, "limit": limit, "offset": offset}
        )
        rows, count = _results(page)
        if count == 0:  # unknown score vs a score with no metrics: ask the score itself
            await self._record(
                f"/score/{sid}", "pgs_id", sid, "Find scores with search_scores(trait_id=...)."
            )
        items = [performance_row(r) for r in rows]
        return await self._stamp(
            {
                "pgs_id": sid,
                "performance": items,
                **page_block(total=count, returned=len(items), limit=limit, offset=offset),
            }
        )

    async def _publication(self, publication_id: str | None, pmid: int | None) -> dict[str, Any]:
        if (publication_id is None) == (pmid is None):
            raise InvalidInputError(
                "Give exactly one of `publication_id` or `pmid`.", field="publication_id"
            )
        if publication_id is not None:
            pid = _check(publication_id, PGP_ID, "publication_id", "PGP000001")
            return await self._record(
                f"/publication/{pid}", "publication_id", pid, "Look the paper up by `pmid` instead."
            )
        if pmid is None or pmid < 1:
            raise InvalidInputError("`pmid` must be a positive integer.", field="pmid")
        rows, _ = _results(await self.client.get_json("/publication/search", {"pmid": pmid}))
        if not rows:
            raise NotFoundError(
                f"The PGS Catalog has no publication with `pmid` {pmid}.",
                field="pmid",
                hint="Only papers that publish or evaluate a PGS are in the catalog.",
            )
        return rows[0]

    async def get_publication(
        self, publication_id: str | None = None, pmid: int | None = None
    ) -> dict[str, Any]:
        """One catalog publication and the scores it developed or evaluated."""
        raw = await self._publication(publication_id, pmid)
        return await self._stamp({"publication": publication_detail(raw)})
