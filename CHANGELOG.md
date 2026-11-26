# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-11-26

### Added

- Paged tools (`get_score_performance`, `resolve_trait`, `search_scores`) report `_meta.pagination` with `total_count`, `has_more` and
  `next_cursor` (`null` where paging is by offset, which then also carries `next_offset`), as
  Response-Envelope Standard v1 §5 asks. The top-level paging fields are unchanged.

## [0.4.0] - 2026-11-26

### Added

- Response-Envelope Standard v1.2: every successful data result carries `_meta.source`,
  `_meta.data_version` (the PGS Catalog release date, e.g. `2026-10-23`) and
  `_meta.retrieved_at` (UTC time of the oldest upstream fetch behind the result; a cache hit
  keeps the time of the fetch that filled its entry).
- Schema tests: every data tool result is validated against the vendored
  `envelope-v1.2.schema.json` (genefoundry-envelope v1.2.0, sha256-pinned).

### Changed

- **Breaking:** the primary payload key is now `results` (lists: `resolve_trait`,
  `search_scores`, `get_score_performance`) or `result` (records: `get_trait`, `get_score`,
  `get_publication`), per Response-Envelope Standard v1 §1. It was `traits`, `scores`,
  `performance`, `trait`, `score` and `publication`.
- Re-vendored `tests/conformance/behaviour.py` from genefoundry-router (v1.2 provenance check).

### Deprecated

- The top-level `data_version` and `retrieved_at` of a data result. Read them from `_meta`;
  the top-level copies will be removed in the next minor release.

## [0.3.3] - 2026-11-19

- `resolve_trait`: a query with no label or synonym match (and a complete first page) is now an honest `not_found` (`isError`) instead of a success, per Response-Envelope §2a. Partial hits become `candidates` flagged `match: "weak"`; `_meta.next_commands` points to `search_scores` for the top candidate, then `mondo_resolve_disease` for name queries. The query is not echoed in the message.

## [0.3.2] - 2026-11-19

### Changed

- A `resolve_trait` miss on a name now suggests `mondo_resolve_disease` in
  `_meta.next_commands` (the fleet's disease front door) and says so in the hint.
- `resolve_trait` description names the returned key (`id`, the `trait_id` other tools take).
- Re-vendored `scripts/surface.py` from genefoundry-router v0.13.1 (Tool-Schema Documentation
  v1.1, rule D1); excluded from ruff like the other vendored files.

### Added

- Guard tests: every description lead states what the tool returns (D1, strict); every
  `next_commands` target names a real tool and real arguments; the fields descriptions promise
  are returned.

## [0.3.1] - 2026-11-18

### Security

- An unknown JSON-RPC method name is no longer echoed in the METHOD_NOT_FOUND error `data`
  (MCP SDK 2 reflects it verbatim in both protocol eras); the not-found guard re-raises a
  fixed `-32601` without data, and the log scrub covers the SDK 2 runner/dispatcher lines
  (`mcp.server.runner`) that echo a caller-supplied method.

## [0.3.0] - 2026-11-18

### Changed

- Upgrade FastMCP 3.4 → 4.2.2 and MCP SDK 1.x → 2.x; supports the 2026-07-28 sessionless
  protocol era alongside the legacy handshake.
- Not-found guard Layer 3 (protocol backstop) ported to the SDK 2 request-handler API; a
  wrapped `resources/read` / `prompts/get` failure keeps JSON-RPC code `-32602` with its fixed,
  input-free message.
- `httpx2` / `httpcore2` loggers (FastMCP 4's HTTP stack) are capped at WARNING like `httpx`.

## [0.2.0] - 2026-11-15

Driven by five rounds of agent UX evaluation (Claude Code, Codex CLI, Antigravity) with only
this server mounted; protocol and results in `docs/benchmarks/`.

### Added

- `response_mode` (`minimal|compact|standard|full`, default `compact`) on `search_scores` and
  `get_score_performance`, per the fleet Response-Envelope Standard. Compact performance pages
  list each evaluation sample set once (`samplesets`).
- `get_score_performance(publication_id=)` keeps only one paper's records.
- `search_scores` selectors combine with AND (`trait_id` + `pmid`, ...), echo
  `matches_per_selector`, and report unknown `pgs_ids` as `missing_pgs_ids`.
- `resolve_trait` rows carry `match` (label, synonym or partial); a hint flags several exact
  matches, a retired ontology ID and an empty name search.
- Argument errors name the pattern and give a ready-to-run corrected call (zero-padded IDs,
  clamped limits, `resolve_trait(query=...)` for a trait name passed as `trait_id`).
- `get_server_capabilities.ancestry_legend`; the 2021 catalog paper in `recommended_citation`.

### Changed

- Trait counts are `score_count` and `score_count_with_descendants` (inclusive);
  `descendant_score_count` is gone.
- The standard catalog licence is stated once per page (`license_default`); other licences
  stay on their row verbatim.
- Performance prose is fenced once per row as `reported` (standard/full); `limit` is capped
  at 50 for every tool.
- `get_trait` lists the first 50 score IDs (`pgs_ids_truncated`); `get_score` lists cohorts
  once per score; cohort and author lists are capped with counts.
- `get_publication` accepts a PubMed ID as a number; its errors name `publication`.


## [0.1.0] - 2026-11-15

### Added

- Read-only MCP server over the live PGS Catalog REST API
  (https://www.pgscatalog.org/rest/), router namespace `pgscatalog`
  ([genefoundry-router#288](https://github.com/berntpopp/genefoundry-router/issues/288)).
- Tools: `resolve_trait`, `get_trait`, `search_scores`, `get_score`,
  `get_score_performance`, `get_publication`, `get_server_capabilities`, `get_diagnostics`.
- Unknown IDs (upstream HTTP 200 `{}`) and obsolete EFO trait IDs map to `not_found`;
  `limit` capped at 50 (25 for performance records); `total`/`truncated` from the upstream
  `count`; per-score `license` passed through verbatim; scoring files linked, never streamed.
- Process-wide politeness limiter (0.6 s spacing, about 100/min, 20,000/UTC day) and an
  in-process TTL cache; no data snapshot, no on-disk state.
- Fleet scaffolding from ucsc-link: unified FastAPI + MCP transport, hardened container
  (non-root 10001, read-only rootfs, `cap_drop: ALL`), NPM deploy overlay, CI, conformance.
