# Agent UX evaluation protocol

How we test pgscatalog-link the way it is used: real agent CLIs, each with only this MCP server
mounted, doing realistic and adversarial PGS Catalog work, then rating the experience. It
follows the fleet's earlier rounds (clinpgx-link `docs/benchmarks/opus-ux-protocol.md`,
the ucsc-link new-MCP evaluation) in a lighter form.

## Agents

Each prompt runs once per agent per round against one local server. The three agents run in
parallel, each working through the prompts in sequence, so 3 sessions run at a time. Rounds 1-4
ran all sessions at once (up to 9), which made speed ratings mostly measure queueing at the
shared upstream rate limit.

| Agent | Invocation (see `scripts/agent_ux_eval.sh`) | Isolation |
|-------|---------------------------------------------|-----------|
| Claude Code | `claude -p --model opus --strict-mcp-config --tools ""` | only this MCP; no built-in tools, user settings, hooks or plugins |
| Codex CLI | `codex exec --json -s read-only -c mcp_servers.<name>.url=...` | read-only sandbox, empty working directory |
| Antigravity (`agy`) | `agy -p` with the server added through `agy mcp add` | empty working directory; other user MCP servers stay mounted, the prompt forbids them |

Record the model each client actually resolved (Claude's `init` event, Codex's config). Never
substitute a model silently. Keep every session, including failed or timed-out ones.

## Tasks

Prompts live in `tasks/` and are frozen before a round. `{SERVER}` is replaced by the mounted
name.

- `A-researcher.md`: a research workflow. Trait resolution, score selection, metadata, licence,
  performance metrics, publications, scoring-file links, release and citation.
- `B-adversarial.md`: retired trait IDs, paging, unknown and malformed IDs, an over-cap limit,
  conflicting selectors, an empty search, an out-of-scope request (computing a PRS) and a
  metric hunt across many records.
- `C-fresh.md`: written and frozen before the final round and never shown earlier. It checks
  that fixes generalise instead of fitting the A/B wording.

Agents get no answer key and no score target. A private answer key, verified against the live
API before round 1, is kept with the run artefacts, outside the repo.

## Ratings

Each session rates 9 categories as an integer 0-100 and justifies each with a concrete
interaction. It also lists its friction points and suggested improvements:

`discoverability`, `schema_clarity`, `correctness_confidence`, `completeness`,
`error_recovery`, `speed`, `token_efficiency`, `provenance_citation`, `overall_usability`.

`scripts/agent_ux_scores.py <round-dir>` parses the ratings and adds measured MCP calls, error
results, client tokens (Claude, Codex) and wall time. A missing rating counts as a failure, not
as 100.

Unexercised categories (added in round 3, following the clinpgx protocol's "an aspect untested
by one task may be evaluated by another"): a session whose trace has no error result cannot
measure error recovery. Its `error_recovery` rating is shown in brackets and left out of the
minimum. Every agent must still rate error recovery in at least one session that hit errors (B
and C always do). agy writes no trace, so its ratings always count.

Speed ratings are subjective and still taken under some contention: the sessions of a round
share one server and its 0.6 s upstream spacing. Single-call cold and warm latency is measured separately
and reported next to the ratings.

## Gate

A round passes when **every category's minimum over all sessions is > 85**. Averages are never
used, so one bad session cannot be hidden. It must also pass all of:

1. I audit every answer against the answer key. A wrong fact the server caused (misleading
   field, dishonest count) blocks the round whatever the self-ratings say.
2. The final round includes `C-fresh.md`.
3. `make ci-local` and the live behaviour probe stay green.

## Improvement loop

1. Run the round: `scripts/agent_ux_eval.sh <out>/round-N`.
2. Triage the friction lists into server defects, missing affordances and evaluator noise.
   Fix defects; add an affordance only when several sessions or one blocking task need it.
   Do not tune wording to one prompt.
3. Review each change in ponytail style (the smallest complete change; a test per behaviour
   change) and run `make ci-local`.
4. Restart the server and rerun every prompt. Never drop a low-scoring session or reword a task
   to raise its score.

The rounds and their scores are written up in `agent-ux-results.md`.
