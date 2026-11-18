# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
