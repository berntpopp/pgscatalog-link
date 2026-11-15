# pgscatalog-link design (2026-11-15)

> Historical record — the v0.1.0 design as built; the live contract is `get_server_capabilities` and the README.

Tracking issue: [genefoundry-router#288](https://github.com/berntpopp/genefoundry-router/issues/288).

## Goal

A read-only MCP backend over the [PGS Catalog](https://www.pgscatalog.org/) REST API that
gives the fleet a polygenic-score dimension: scores, the traits they predict, their source
publications and published performance metrics. Metadata only. Scoring files are linked,
never streamed or computed on.

## Template

The repo is cloned from `ucsc-link`, the newest live-API backend with no data snapshot. It
keeps the MCP plane (envelope, not-found guard, untrusted-text fencing, metrics), the
origin-guarded rate-limited cached client, the container hardening and the CI. The
pagination block follows mavedb-link `page_block`.

## Upstream facts (verified live 2026-11-15)

| Fact | Consequence |
|------|-------------|
| `/rest/info` gives `rest_api.version` (1.8.6) and `latest_release.date` (2026-10-23) | stamped as `data_version` on every payload |
| Unknown `score/`, `trait/` or `publication/` ID answers `200 {}` | mapped to `not_found` naming the argument |
| Obsolete EFO trait (e.g. `EFO_0000305`) answers `{}`; current ID is `MONDO_0004989` | `not_found` with a `resolve_trait` hint |
| `performance/search?pgs_id=<unknown>` answers `count: 0` | the score itself is checked, so an unknown score is `not_found`, not empty |
| `limit` > 250 answers `400 {"message": ...}` | `invalid_input`, field `limit`; our caps are 50 (25 for performance) |
| Pages carry `count`/`next`/`previous`, offset/limit | `total` = `count` exactly |
| `trait/{id}?include_children=1` gives `associated_pgs_ids` and `child_associated_pgs_ids` | `search_scores(trait_id, include_children)` pages over that ID set |
| `score/search?pgs_ids=a,b` silently drops unknown IDs | reported as `missing_pgs_ids` |
| Each score has a `license` string | passed through verbatim |
| No documented rate limit found | default 0.6 s spacing (~100/min), 20,000/UTC day |

## Tool surface

`get_server_capabilities`, `get_diagnostics`, `resolve_trait`, `get_trait`,
`search_scores`, `get_score`, `get_score_performance`, `get_publication`. All use Tier-1
verbs (Tool-Naming Standard v1.1) and are read-only with no `outputSchema`.

## Deliberately out of scope

- Streaming scoring-file weights, and score calculation (pgsc_calc).
- A `response_mode` parameter. Rows are compact by default.
- Sample-set, cohort and ancestry-category endpoints. They are reachable through score and
  performance rows.
