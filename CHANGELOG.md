# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
