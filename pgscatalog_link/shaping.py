"""Pure shapers: turn native PGS Catalog records into compact, honest payload rows.

Identifiers, numbers and controlled vocabularies pass through verbatim. Free-text prose
written by submitters (titles, trait descriptions, phenotyping, covariates, comments) is
fenced as ``untrusted_text``. The per-score ``license`` is passed through verbatim: it is
the author-set reuse term and must never be paraphrased.
"""

from __future__ import annotations

import re
from typing import Any

from pgscatalog_link.mcp.untrusted_content import fence_untrusted_text

SITE = "https://www.pgscatalog.org"
PGS_ID = re.compile(r"^PGS\d{6}$")
PGP_ID = re.compile(r"^PGP\d{6}$")
#: Ontology CURIE as the catalog writes it (EFO_0001645, MONDO_0004989, HP_0000822, ...).
TRAIT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}_[A-Za-z0-9]{1,20}$")


def fence(raw: Any, record_id: str) -> dict[str, Any] | None:
    """Fence one upstream prose value (``None``/empty stays ``None``)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return fence_untrusted_text(raw, source="pgscatalog", record_id=record_id).model_dump(
        mode="json"
    )


def page_block(*, total: int, returned: int, limit: int, offset: int) -> dict[str, Any]:
    """Uniform pagination block; ``total`` is the exact upstream/derived count."""
    truncated = offset + returned < total
    return {
        "total": total,
        "returned": returned,
        "limit": limit,
        "offset": offset,
        "truncated": truncated,
        "next_offset": offset + returned if truncated else None,
    }


def publication_ref(pub: dict[str, Any] | None) -> dict[str, Any] | None:
    """Citation-sized reference to a PGP publication (no prose)."""
    if not pub:
        return None
    return {
        "id": pub.get("id"),
        "pmid": pub.get("PMID"),
        "doi": pub.get("doi"),
        "first_author": pub.get("firstauthor"),
        "journal": pub.get("journal"),
        "date_publication": pub.get("date_publication"),
    }


#: GWAS samples can list 40+ cohorts, repeated across samples; keep the first few and a count.
MAX_COHORTS = 10


def _cohort_union(raw: dict[str, Any]) -> dict[str, Any]:
    """All cohorts of a score's GWAS and training samples, listed once."""
    samples = (raw.get("samples_variants") or []) + (raw.get("samples_training") or [])
    names = list(
        dict.fromkeys(c.get("name_short") for s in samples for c in s.get("cohorts") or [])
    )
    cap = MAX_COHORTS * 3
    return {
        "cohorts": names[:cap],
        "cohort_count": len(names),
        "cohorts_truncated": len(names) > cap,
    }


def _sample(sample: dict[str, Any], with_cohorts: bool = True) -> dict[str, Any]:
    cohorts = [c.get("name_short") for c in sample.get("cohorts") or []]
    out = {
        "sample_number": sample.get("sample_number"),
        "cases": sample.get("sample_cases"),
        "controls": sample.get("sample_controls"),
        "ancestry_broad": sample.get("ancestry_broad"),
        "ancestry_country": sample.get("ancestry_country"),
        "source_gwas_catalog": sample.get("source_GWAS_catalog"),
        "cohorts": cohorts[:MAX_COHORTS],
        "cohort_count": len(cohorts),
        "cohorts_truncated": len(cohorts) > MAX_COHORTS,
    }
    if not with_cohorts:  # get_score lists them once for the whole score
        del out["cohorts"], out["cohorts_truncated"]
    return out


def match_kind(raw: dict[str, Any], query: str) -> str:
    """How a trait matched a search: its label, one of its synonyms, or only partially."""
    q = query.strip().casefold()
    if str(raw.get("label", "")).casefold() == q or str(raw.get("id", "")).casefold() == q:
        return "label"
    if any(str(s).casefold() == q for s in raw.get("trait_synonyms") or []):
        return "synonym"
    return "partial"


def trait_summary(raw: dict[str, Any]) -> dict[str, Any]:
    """A trait row for resolve_trait: identity, categories and score counts."""
    direct = raw.get("associated_pgs_ids") or []
    child = raw.get("child_associated_pgs_ids") or []
    return {
        "id": raw.get("id"),
        "label": raw.get("label"),
        "ontology_url": raw.get("url"),
        "categories": raw.get("trait_categories") or [],
        "synonyms": (raw.get("trait_synonyms") or [])[:10],
        "score_count": len(direct),
        "score_count_with_descendants": len(set(child) | set(direct)),
        "url": f"{SITE}/trait/{raw.get('id')}/",
    }


#: get_trait lists at most this many score IDs; search_scores(trait_id) pages all of them.
MAX_TRAIT_IDS = 50


def _id_list(key: str, ids: list[str]) -> dict[str, Any]:
    return {key: ids[:MAX_TRAIT_IDS], f"{key}_truncated": len(ids) > MAX_TRAIT_IDS}


def trait_detail(raw: dict[str, Any], *, include_children: bool) -> dict[str, Any]:
    """Full trait record; descendant scores only when asked for."""
    trait_id = str(raw.get("id"))
    out = trait_summary(raw)
    out["synonyms"] = raw.get("trait_synonyms") or []
    out["mapped_terms"] = raw.get("trait_mapped_terms") or []
    out["description"] = fence(raw.get("description"), trait_id)
    direct = raw.get("associated_pgs_ids") or []
    out.update(_id_list("pgs_ids", direct))
    if include_children:
        out.update(
            _id_list(
                "descendant_pgs_ids",
                sorted(set(raw.get("child_associated_pgs_ids") or []) - set(direct)),
            )
        )
        out["child_traits"] = [
            {"id": c.get("id"), "label": c.get("label")} for c in raw.get("child_traits") or []
        ]
    return out


def _pub_id(pub: dict[str, Any] | None) -> dict[str, Any] | None:
    """The source paper in list rows: enough to cite or look it up (get_publication)."""
    ref = publication_ref(pub)
    return {k: ref[k] for k in ("id", "pmid", "first_author")} if ref else None


def _ancestry(raw: Any) -> dict[str, Any]:
    """Per stage (gwas/dev/eval): % by broad ancestry code and the sample count."""
    if not isinstance(raw, dict):
        return {}
    return {
        stage: {"dist": v.get("dist") or {}, "count": v.get("count")}
        for stage, v in raw.items()
        if isinstance(v, dict)
    }


#: Fleet response_mode canon (Response-Envelope Standard v1 §3); compact is the default.
RESPONSE_MODES = ("minimal", "compact", "standard", "full")


def score_row(raw: dict[str, Any], mode: str) -> dict[str, Any]:
    """A search_scores row at one response_mode (narrower modes are projections)."""
    if mode == "minimal":
        return {"id": raw.get("id"), "name": raw.get("name")}
    row = score_summary(raw)
    if mode == "compact":
        for key in ("traits", "weight_type", "date_release", "url"):
            row.pop(key)
        row["ancestry_distribution"] = {
            stage: v["dist"] for stage, v in row["ancestry_distribution"].items()
        }
    return row


def score_summary(raw: dict[str, Any]) -> dict[str, Any]:
    """A score row for search_scores: what it predicts, how it was built, who may use it."""
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "trait_reported": raw.get("trait_reported"),
        "traits": [
            {"id": t.get("id"), "label": t.get("label")} for t in raw.get("trait_efo") or []
        ],
        "method_name": raw.get("method_name"),
        "variants_number": raw.get("variants_number"),
        "variants_genomebuild": raw.get("variants_genomebuild"),
        "weight_type": raw.get("weight_type"),
        "ancestry_distribution": _ancestry(raw.get("ancestry_distribution")),
        "publication": _pub_id(raw.get("publication")),
        "date_release": raw.get("date_release"),
        "license": raw.get("license"),
        "url": f"{SITE}/score/{raw.get('id')}/",
    }


def score_detail(raw: dict[str, Any]) -> dict[str, Any]:
    """Full score metadata; the weights themselves stay in the linked scoring files."""
    score_id = str(raw.get("id"))
    out = score_summary(raw)
    out["ancestry_distribution"] = raw.get("ancestry_distribution") or {}  # keeps `multi`
    out["publication"] = publication_ref(raw.get("publication"))
    harmonized = raw.get("ftp_harmonized_scoring_files") or {}
    out.update(
        {
            "trait_additional": fence(raw.get("trait_additional"), score_id),
            "method_params": fence(raw.get("method_params"), score_id),
            "variants_interactions": raw.get("variants_interactions"),
            "matches_publication": raw.get("matches_publication"),
            "samples_variants": [_sample(s, False) for s in raw.get("samples_variants") or []],
            "samples_training": [_sample(s, False) for s in raw.get("samples_training") or []],
            **_cohort_union(raw),
            "scoring_files": {
                "note": "each harmonized file holds the same variants_number rows as the "
                "original, with GRCh37/GRCh38 positions added (hm_pos is empty where a "
                "variant could not be mapped); the catalog publishes no per-build mapped "
                "count (its file headers leave HmPOS_match_pos null)",
                "original": raw.get("ftp_scoring_file"),
                "harmonized": {
                    build: (files or {}).get("positions") for build, files in harmonized.items()
                },
            },
        }
    )
    return out


def _metrics(rows: Any, compact: bool) -> list[dict[str, Any]]:
    if not compact:
        return list(rows or [])
    return [{k: v for k, v in m.items() if k != "name_long"} for m in rows or []]


def compact_samples(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """An evaluation sample set without country strings and empty fields."""
    keep = ("sample_number", "cases", "controls", "ancestry_broad", "cohorts", "cohort_count")
    samples = performance_row(raw, "full")["sampleset"]["samples"]
    return [{k: s[k] for k in keep if s.get(k) not in (None, [])} for s in samples]


def performance_row(raw: dict[str, Any], mode: str = "full") -> dict[str, Any]:
    """One PPM performance record at one response_mode.

    standard/full: the evaluation samples inline and the submitter's phenotype, covariate
    and comment prose fenced once as ``reported``. compact: metrics with short names and a
    sampleset ID (the page lists each set once). minimal: compact without the publication.
    """
    compact = mode in ("minimal", "compact")
    ppm_id = str(raw.get("id"))
    sampleset = raw.get("sampleset") or {}
    metrics = raw.get("performance_metrics") or {}
    out: dict[str, Any] = {
        "id": ppm_id,
        "pgs_id": raw.get("associated_pgs_id"),
        "publication": publication_ref(raw.get("publication")),
        "sampleset": {
            "id": sampleset.get("id"),
            "samples": [_sample(s) for s in sampleset.get("samples") or []],
        },
        "effect_sizes": _metrics(metrics.get("effect_sizes"), compact),
        "classification_metrics": _metrics(metrics.get("class_acc"), compact),
        "other_metrics": _metrics(metrics.get("othermetrics"), compact),
    }
    if compact:  # metric scans: cite the paper by ID; sample sets are listed once per page
        out["publication"] = _pub_id(raw.get("publication"))
        out["sampleset"] = sampleset.get("id")
        if mode == "minimal":
            del out["publication"]
        for key in [
            k for k in ("effect_sizes", "classification_metrics", "other_metrics") if not out[k]
        ]:
            del out[key]  # omit, don't null-pad
    else:
        parts = [
            f"{label}: {raw[key].strip()}"
            for label, key in (
                ("phenotype", "phenotyping_reported"),
                ("covariates", "covariates"),
                ("comments", "performance_comments"),
            )
            if isinstance(raw.get(key), str) and raw[key].strip()
        ]
        out["reported"] = fence("\n".join(parts), ppm_id)
    return out


#: The catalog's standard reuse terms, carried by most scores.
STANDARD_LICENSE = (
    "PGS obtained from the Catalog should be cited appropriately, and used in accordance "
    "with any licensing restrictions set by the authors. See EBI Terms of Use "
    "(https://www.ebi.ac.uk/about/terms-of-use/) for additional details."
)


def factor_license(rows: list[dict[str, Any]]) -> str | None:
    """Drop the standard terms from rows that carry them; return them once (else None).

    Repeating the boilerplate per row costs ~60 tokens each. A row with any other licence
    keeps its own verbatim ``license``, so the meaning never depends on the page.
    """
    hit = False
    for row in rows:
        if row.get("license") == STANDARD_LICENSE:
            del row["license"]
            hit = True
    return STANDARD_LICENSE if hit else None


MAX_AUTHORS = 10


def _authors(raw: Any) -> dict[str, Any]:
    """First authors plus the full count (consortium papers list hundreds)."""
    names = [a.strip() for a in str(raw or "").split(",") if a.strip()]
    shown = ", ".join(names[:MAX_AUTHORS]) + (", et al." if len(names) > MAX_AUTHORS else "")
    return {"authors": shown or None, "author_count": len(names)}


def publication_detail(raw: dict[str, Any]) -> dict[str, Any]:
    """A PGP publication with the scores it developed and evaluated."""
    pub_id = str(raw.get("id"))
    associated = raw.get("associated_pgs_ids") or {}
    out = publication_ref(raw) or {}
    out.update(
        {
            "title": fence(raw.get("title"), pub_id),
            **_authors(raw.get("authors")),
            "date_release": raw.get("date_release"),
            "developed_pgs_ids": associated.get("development") or [],
            "evaluated_pgs_ids": associated.get("evaluation") or [],
            "url": f"{SITE}/publication/{pub_id}/",
        }
    )
    return out
