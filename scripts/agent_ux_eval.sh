#!/usr/bin/env bash
# Run the agent UX evaluation: every task prompt x every agent CLI, in parallel, each session in
# its own empty directory with only this MCP server mounted. See docs/benchmarks/agent-ux-protocol.md.
#
#   scripts/agent_ux_eval.sh <out-dir> [mcp-url] [task-glob]
#
# The server must already be running (python server.py --transport unified --port 18493).
set -uo pipefail
OUT=${1:?usage: agent_ux_eval.sh <out-dir> [mcp-url] [task-glob]}
URL=${2:-http://127.0.0.1:18493/mcp}
TASKS=${3:-"$(dirname "$0")/../docs/benchmarks/tasks/[A-B]-*.md"}
NAME=eval-pgscatalog-link
TIMEOUT=${TIMEOUT:-1200}
mkdir -p "$OUT" && OUT=$(cd "$OUT" && pwd)  # sessions cd into their own dirs
curl -sf "${URL%/mcp}/health" >/dev/null || { echo "server not reachable at $URL" >&2; exit 1; }
# agy has no per-session MCP flag: register (idempotent) in its user config.
agy mcp add "$NAME" "$URL" >/dev/null

run() {  # run <agent> <task-file>
  local agent=$1 task=$2 id dir prompt t0
  id=$(basename "$task" .md)-$agent; dir=$OUT/$id; mkdir -p "$dir/cwd"
  prompt=$(sed "s/{SERVER}/$NAME/g" "$task"); printf '%s\n' "$prompt" > "$dir/prompt.txt"
  t0=$(date +%s.%N)
  cd "$dir/cwd" || return
  case $agent in
    claude) timeout "$TIMEOUT" claude -p "$prompt" --model opus \
        --mcp-config "{\"mcpServers\":{\"$NAME\":{\"type\":\"http\",\"url\":\"$URL\"}}}" \
        --strict-mcp-config --tools "" --allowedTools "mcp__${NAME}__*" --setting-sources project \
        --no-session-persistence --output-format stream-json --verbose \
        < /dev/null > "$dir/trace.jsonl" 2> "$dir/stderr.log" ;;
    codex) timeout "$TIMEOUT" codex exec --json --skip-git-repo-check -s read-only \
        -o "$dir/final.txt" -c "mcp_servers.eval_pgscatalog.url=\"$URL\"" \
        -c 'mcp_servers.eval_pgscatalog.default_tools_approval_mode="approve"' "$prompt" \
        < /dev/null > "$dir/trace.jsonl" 2> "$dir/stderr.log" ;;
    agy) timeout "$TIMEOUT" agy -p "$prompt" --dangerously-skip-permissions \
        --print-timeout "$((TIMEOUT - 60))s" < /dev/null > "$dir/final.txt" 2> "$dir/stderr.log" ;;
  esac
  echo "rc=$? wall_s=$(echo "$(date +%s.%N) - $t0" | bc)" > "$dir/run.txt"
}

# One session per agent at a time (3 concurrent): prompts run in sequence, agents in parallel.
for agent in claude codex agy; do
  ( for task in $TASKS; do run "$agent" "$task"; done ) &
done
wait
python3 "$(dirname "$0")/agent_ux_scores.py" "$OUT"
