#!/usr/bin/env bash
# PreToolUse:Edit|Write — protect immutable artifacts and the harness itself. Exit 2 = BLOCK.
# From veyqon-dev-scaffold; adapted for the Flow fork 19 Sep 2026 (adds: the agent may not edit
# the harness that judges it — gate scripts, hooks, settings).
set -uo pipefail
INPUT=$(cat)
F=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
[ -z "$F" ] && exit 0

# ---- The harness judges the agent; the agent does not edit the harness -------
case "$F" in
  *scripts/run-tests.sh|*scripts/doctor.sh|*scripts/hooks/*|*.claude/settings.json)
    {
      echo "BLOCKED: $F is part of the harness that verifies your work."
      echo "If it is wrong, STOP and say what is wrong and why. A human changes it."
    } >&2
    exit 2 ;;
esac

# ---- ADRs are immutable: supersede, never edit -----------------------------
if echo "$F" | grep -q "brain/20-adr/" && [ -f "$F" ]; then
  {
    echo "BLOCKED: ADRs are immutable."
    echo "Write a NEW ADR that supersedes this one, then set the old one's status: superseded."
  } >&2
  exit 2
fi

# ---- features.json: the agent may ONLY flip `passes` -----------------------
if echo "$F" | grep -q 'features\.json$' && [ -f "$F" ]; then
  NEW=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
  if [ -z "$NEW" ]; then
    {
      echo "BLOCKED: use Write (whole file), not Edit, on features.json — so this guard can"
      echo "verify you changed nothing but 'passes'."
    } >&2
    exit 2
  fi
  OLD_KEYS=$(jq -S '[.features[] | {id, description}]' "$F" 2>/dev/null)
  NEW_KEYS=$(echo "$NEW" | jq -S '[.features[] | {id, description}]' 2>/dev/null)
  if [ -z "$NEW_KEYS" ]; then
    echo "BLOCKED: the new features.json is not valid JSON, or has no .features array." >&2
    exit 2
  fi
  if [ "$OLD_KEYS" != "$NEW_KEYS" ]; then
    {
      echo "BLOCKED: features.json entries were added, removed, or reworded."
      echo "You may ONLY flip 'passes'. If the contract is wrong, STOP and say so."
    } >&2
    exit 2
  fi
fi
exit 0
