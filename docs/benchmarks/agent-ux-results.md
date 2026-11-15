# Agent UX evaluation results (2026-11-15)

> Historical record — five rounds run against v0.1.0 and the changes that became v0.2.0; the live contract is `get_server_capabilities` and the README.

Method: [`agent-ux-protocol.md`](agent-ux-protocol.md). Agents: Claude Code 2.1.325
(`claude-opus-5-5`), Codex CLI 0.164.0 (its configured default model), Antigravity `agy` 1.5.9
(Gemini 4 Carbon High). Prompts: A (researcher) and B (adversarial) in every round. The
held-out C was frozen after round 2 and run in rounds 3-5. Raw traces are machine-local and
are not committed.

## Minimum rating per category (0-100, over all sessions of the round)

| Round | discov | schema | correct | complete | error | speed | tokens | provenance | overall |
|------:|------:|------:|------:|------:|------:|------:|------:|------:|------:|
| 1 (v0.1.0) | 82 | 78 | 85 | 75 | 60 | 84 | 55 | 92 | 80 |
| 2 | 88 | 85 | 85 | 78 | 75 | 85 | 62 | 92 | 84 |
| 3 (+C) | 88 | 83 | 88 | 84 | 70 | 70 | 68 | 92 | 83 |
| 4 | 88 | 87 | 85 | 82 | 84 | 78 | 72 | 90 | 85 |
| 5 | 85 | 85 | 85 | 85 | 85 | 72 | 76 | 90 | 86 |

Rows 1 and 2 are as scored at the time. Later rescoring leaves out untested `error_recovery`
ratings: it raises round 1's error minimum to 72 and round 2's to 86, and changes nothing else.

In round 5, Codex and agy rate every category at 85 or above except token efficiency (76-87).
Most of the round-5 minimums come from Claude. Its B session rated everything exactly 85, and
its speed ratings (72, 78) cite the slow upstream performance endpoint.

**Gate not reached (> 85 everywhere).** The open categories are:

- **Speed: upstream-bound.** Warm calls take 2-4 ms and our client's round trip is 0.3-0.6 s.
  But the catalog's `/performance/search` itself takes 6-12 s for scores with many records:
  PGS000006 took 12 s at `limit=10`, measured directly with curl. Cache hits make repeats
  instant. Nothing on our side can make the first call faster.
- **Token efficiency: improved after round 5, not re-measured by agents.** The fleet
  `response_mode` (default `compact`) landed after round 5. It replaced the round-4 `compact`
  booleans, which were not the fleet standard. Payload sizes:

| Call | Round 1 | v0.2.0 default |
|------|--------:|---------------:|
| `search_scores(trait_id=T2D, limit=20)` | 17.9 KB | 9.1 KB |
| `get_score(PGS000018)` | 6.2 KB | 4.4 KB |
| `get_score_performance(PGS000018)` (10 rows) | 13.7 KB | 4.3 KB |
| `get_score_performance(PGS000001, limit=25)` | 28.3 KB (2 calls) | 7.4 KB |

## Answer audit

Every answer was checked against an answer key verified live before round 1. No wrong fact
was caused by the server in any round.

- Round 3: one Claude B session picked MONDO_0007254 ("breast cancer") over MONDO_0004989
  ("breast carcinoma") as the replacement for the retired EFO_0000305. Neither the catalog nor
  EBI OLS maps that ID, so both readings are defensible, and `resolve_trait` now flags the two
  exact matches.
- Round 5: 9 of 9 sessions correct.

## What changed because of the agents (v0.2.0)

- **Every round:** payload size. The standard licence is stated once per page, cohort and
  author lists are capped with counts, performance prose is fenced once per row, sample sets
  are listed once per page, and the fleet `response_mode` arrived.
- **Error recovery:** errors name the pattern and give an executable fix (zero-padded IDs,
  clamped limits, `resolve_trait(query=...)` for a trait name), not a generic capabilities
  call.
- **Missing affordances:** `publication_id` on performance records, AND-combined
  `search_scores` selectors with `matches_per_selector`, inclusive `score_count_with_descendants`,
  an ancestry legend, and trait `match` kinds with an ambiguity hint.
- **Caught by the ponytail review, not the agents:**
  - A fix suggestion echoed unsanitised caller text.
  - Zero-padding used the wrong prefix (PGP→PGS).
  - A clamped-limit suggestion failed again.
  - Unknown `pgs_ids` disappeared silently in an AND filter.
  - A `resolve_trait({})` recovery step could not be run.

## Declined, with reason

- **A `replaced_by` crosswalk for retired EFO IDs.** Neither the catalog API nor its website
  nor EBI OLS maps EFO_0000305, so any mapping would be invented.
- **Harmonized per-build variant counts.** The files keep every original row, and their
  headers leave `HmPOS_match_pos` null. The catalog publishes no such count; `get_score` says
  so.
- **Metric, ancestry and sort filters; field projection beyond `response_mode`.** These are
  not upstream filters. Each would mean fetching and filtering every page here; revisit if
  requests repeat.
- **Text and `structuredContent` both carrying the JSON.** This is FastMCP's standard return
  shape, used by the whole fleet.
