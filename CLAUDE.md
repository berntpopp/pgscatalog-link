# CLAUDE.md

**Read [AGENTS.md](AGENTS.md) first** — it is the authoritative contributor and agent guide.

Essentials:

- Read-only MCP server over the PGS Catalog REST API: polygenic scores, traits, publications,
  performance metrics. Live calls only; no data snapshot.
- Data plane returns plain dicts and raises typed errors; `run_mcp_tool` owns the envelope.
- Upstream answers HTTP 200 `{}` for unknown IDs and empty for obsolete EFO traits: both are
  `not_found`. `limit` is capped at 250 (upstream 400s above it).
- Per-score `license` passes through verbatim; scoring files are linked, never streamed.
- Every upstream call goes through the process-wide `RateLimiter` — respect it in live tests.
- FastMCP 3.x is post-training-cutoff: verify symbols against the installed package.
- Gate: `make ci-local` (serialize it on shared machines). Never `gh release create`.
