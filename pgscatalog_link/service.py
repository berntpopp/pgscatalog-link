"""PGS Catalog data plane: validate identifiers, query the REST API, shape honest payloads.

Returns plain dicts and raises typed :mod:`pgscatalog_link.exceptions` errors; the MCP
envelope owns ``success``/``_meta``. The catalog answers an unknown identifier with
``200 {}`` and an unknown or obsolete trait in a search with ``count: 0``; both are
turned into ``not_found`` naming the offending argument, never a silent empty list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pgscatalog_link.api.client import FETCH_TIMES, PgsClient
from pgscatalog_link.exceptions import InvalidInputError, NotFoundError, UpstreamSchemaError
from pgscatalog_link.mcp.next_commands import cmd
from pgscatalog_link.shaping import (
    PGP_ID,
    PGS_ID,
    TRAIT_ID,
    compact_samples,
    factor_license,
    match_kind,
    page_block,
    performance_row,
    publication_detail,
    score_detail,
    score_row,
    trait_detail,
    trait_summary,
)

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
#: One fenced `reported` block per performance row keeps 50 rows under the 128-fence cap.
MAX_PERFORMANCE_LIMIT = 50
MAX_PGS_IDS = 50


def _retrieved_at() -> str:
    """The oldest upstream fetch behind this call (a cache hit keeps its fetch time)."""
    times = FETCH_TIMES.get()
    when = datetime.fromtimestamp(min(times), UTC) if times else datetime.now(UTC)
    return when.isoformat(timespec="seconds").replace("+00:00", "Z")


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
        payload["retrieved_at"] = _retrieved_at()
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
        items = [{**trait_summary(r), "match": match_kind(r, term)} for r in rows]
        payload: dict[str, Any] = {
            "query": term,
            "traits": items,
            **page_block(total=count, returned=len(items), limit=limit, offset=offset),
        }
        exact = [t["id"] for t in items if t["match"] != "partial"]
        if not exact and offset == 0 and not payload["truncated"]:
            raise self._trait_miss(term, items)
        if len(exact) > 1:
            payload["hint"] = (
                f"{len(exact)} traits match this name exactly ({', '.join(exact)}); they are "
                "different ontology terms (often parent and child): compare their labels and "
                "score counts, or use get_trait(include_children=true)."
            )
        return await self._stamp(payload)

    @staticmethod
    def _trait_miss(term: str, items: list[dict[str, Any]]) -> NotFoundError:
        """No label/synonym match (Envelope §2a): not_found; partial hits are weak candidates.

        The unmatched term is never forwarded into a step (GTS-CORE-TXT-04).
        """
        candidates = [{**t, "match": "weak"} for t in items]
        steps = [cmd("search_scores", trait_id=t["id"]) for t in candidates[:1]]
        if TRAIT_ID.fullmatch(term):
            hint = (
                "No current catalog trait has this ID. IDs the catalog retired (many EFO "
                "terms moved to MONDO) are not mapped to their replacement: search by the "
                "trait's name instead."
            )
        else:
            hint = (
                "No trait matched by label or synonym; try a broader name or a synonym. For a "
                "disease, mondo_resolve_disease gives its Mondo ID and synonyms to search with."
            )
        extra: dict[str, Any] = {"field": "query", "hint": hint, "candidates": candidates}
        if steps:
            extra["next_commands"] = steps
        return NotFoundError("No catalog trait matches this query by label or synonym.", **extra)

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
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        """(selector, matching score IDs in PGS ID order, requested pgs_ids that don't exist)."""
        if include_children and trait_id is None:
            raise InvalidInputError(
                "`include_children` only applies with `trait_id`.", field="include_children"
            )
        selector: dict[str, Any] = {}
        sets: list[set[str]] = []
        missing: list[str] = []
        if trait_id is not None:
            raw = await self._trait(trait_id)
            ids = set(raw.get("associated_pgs_ids") or [])
            if include_children:
                ids |= set(raw.get("child_associated_pgs_ids") or [])
            selector.update(trait_id=raw["id"], include_children=include_children)
            sets.append(ids)
        if publication_id is not None or pmid is not None:
            pub = await self._publication(publication_id, pmid)
            associated = pub.get("associated_pgs_ids") or {}
            selector["publication_id"] = pub["id"]
            if pmid is not None:
                selector["pmid"] = pmid
            sets.append(
                set(associated.get("development") or []) | set(associated.get("evaluation") or [])
            )
        if pgs_ids is not None:
            if not 1 <= len(pgs_ids) <= MAX_PGS_IDS:
                raise InvalidInputError(f"`pgs_ids` takes 1-{MAX_PGS_IDS} IDs.", field="pgs_ids")
            wanted = list(dict.fromkeys(_check(v, PGS_ID, "pgs_ids", "PGS000001") for v in pgs_ids))
            selector["pgs_ids"] = wanted
            if not sets:  # an explicit list keeps the caller's order
                known = await self._fetch_scores(wanted)
                missing = [i for i in wanted if i not in known]
            else:
                outside = [i for i in wanted if not all(i in x for x in sets)]
                known = await self._fetch_scores(outside)
                missing = [i for i in outside if i not in known]
            if len(missing) == len(wanted):
                raise NotFoundError(
                    "None of the requested `pgs_ids` exist in the PGS Catalog.", field="pgs_ids"
                )
            if not sets:
                return selector, [i for i in wanted if i not in missing], missing
            sets.append(set(wanted))
        if len(sets) > 1:  # why an AND result is small or empty
            selector["matches_per_selector"] = [len(x) for x in sets]
        return selector, sorted(set.intersection(*sets)), missing

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
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Scores matching every given selector (trait, publication, ID list); none = all."""

        def shape(raw: dict[str, Any]) -> dict[str, Any]:
            return score_row(raw, response_mode)

        _page_args(limit, offset, MAX_LIMIT)
        if not any(v is not None for v in (trait_id, publication_id, pmid, pgs_ids)):
            if include_children:
                raise InvalidInputError(
                    "`include_children` only applies with `trait_id`.", field="include_children"
                )
            return await self._all_scores(limit, offset, shape)
        selector, ids, missing = await self._ids_for(
            trait_id, include_children, publication_id, pmid, pgs_ids
        )
        window = ids[offset : offset + limit]
        found = await self._fetch_scores(window)
        items = [shape(found[i]) for i in window if i in found]
        payload = {
            "selector": selector,
            "license_default": factor_license(items),
            "scores": items,
            # page over the ID window so an ID upstream drops can never stall next_offset
            **page_block(total=len(ids), returned=len(window), limit=limit, offset=offset),
            "returned": len(items),
        }
        missing += [i for i in window if i not in found]
        if missing:
            payload["missing_pgs_ids"] = missing
        return await self._stamp(payload)

    async def _fetch_scores(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Score records by ID in one request (<= 50 IDs); unknown IDs are simply absent."""
        if not ids:
            return {}
        page = await self.client.get_json(
            "/score/search", {"pgs_ids": ",".join(ids), "limit": len(ids)}
        )
        return {str(r.get("id")): r for r in _results(page)[0]}

    async def _all_scores(self, limit: int, offset: int, shape: Any) -> dict[str, Any]:
        """No selector: page through the whole catalog in its native (PGS ID) order."""
        page = await self.client.get_json("/score/all", {"limit": limit, "offset": offset})
        rows, count = _results(page)
        items = [shape(r) for r in rows]
        return await self._stamp(
            {
                "selector": {"all": True},
                "license_default": factor_license(items),
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

    async def get_score_performance(
        self,
        pgs_id: str,
        limit: int,
        offset: int,
        publication_id: str | None = None,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Published performance metrics (PPM) of one score, optionally from one publication."""
        _page_args(limit, offset, MAX_PERFORMANCE_LIMIT)
        sid = _check(pgs_id, PGS_ID, "pgs_id", "PGS000001")
        params: dict[str, Any] = {"pgs_id": sid, "limit": limit, "offset": offset}
        if publication_id is not None:
            params["pgp_id"] = _check(publication_id, PGP_ID, "publication_id", "PGP000001")
        rows, count = _results(await self.client.get_json("/performance/search", params))
        if count == 0:  # an unknown ID vs genuinely no metrics: never a silent empty filter
            await self._record(
                f"/score/{sid}", "pgs_id", sid, "Find scores with search_scores(trait_id=...)."
            )
            if publication_id is not None:
                await self._publication(params["pgp_id"], None)
        items = [performance_row(r, response_mode) for r in rows]
        extra: dict[str, Any] = {}
        if response_mode == "compact":  # records often share a cohort: list each set once
            extra["samplesets"] = {
                str(r["sampleset"]["id"]): compact_samples(r)
                for r in rows
                if isinstance(r.get("sampleset"), dict) and r["sampleset"].get("id")
            }
        return await self._stamp(
            {
                "pgs_id": sid,
                "publication_id": params.get("pgp_id"),
                "performance": items,
                **extra,
                **page_block(total=count, returned=len(items), limit=limit, offset=offset),
            }
        )

    async def _publication(
        self, publication_id: str | None, pmid: int | None, field: str | None = None
    ) -> dict[str, Any]:
        if (publication_id is None) == (pmid is None):
            raise InvalidInputError(
                "Give exactly one of `publication_id` or `pmid`.", field="publication_id"
            )
        if publication_id is not None:
            pid = _check(publication_id, PGP_ID, field or "publication_id", "PGP000001")
            return await self._record(
                f"/publication/{pid}",
                field or "publication_id",
                pid,
                "Look the paper up by its PubMed ID instead.",
            )
        if pmid is None or pmid < 1:
            raise InvalidInputError("`pmid` must be a positive integer.", field=field or "pmid")
        rows, _ = _results(await self.client.get_json("/publication/search", {"pmid": pmid}))
        if not rows:
            raise NotFoundError(
                f"The PGS Catalog has no publication with PubMed ID {pmid}.",
                field=field or "pmid",
                hint="Only papers that publish or evaluate a PGS are in the catalog.",
            )
        return rows[0]

    async def get_publication(
        self, publication_id: str | None = None, pmid: int | None = None, field: str | None = None
    ) -> dict[str, Any]:
        """One catalog publication and the scores it developed or evaluated."""
        raw = await self._publication(publication_id, pmid, field)
        return await self._stamp({"publication": publication_detail(raw)})
