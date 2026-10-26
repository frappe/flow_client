#!/usr/bin/env bash
# PreToolUse:Bash — block destructive or out-of-bounds commands. Exit 2 = deny.
# Adapted from veyqon-dev-scaffold for the Flow fork, 19 Sep 2026.
INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

deny() { echo "BLOCKED: $1 — denied by guard-bash." >&2; exit 2; }

BLOCK=(
  "rm -rf /"
  "rm -rf ~"
  "rm -rf \$HOME"
  "git push --force"
  "git push -f"
  "git reset --hard"
  "git clean -fd"
  "bench drop-site"
  "DROP DATABASE"
  "--force-recreate"
  "docker compose up"
  "docker-compose up"
)
for pat in "${BLOCK[@]}"; do
  echo "$CMD" | grep -qiF -- "$pat" && deny "'$pat' is destructive"
done

# Kill by name/pattern can hit unrelated processes (bench, other stacks on this laptop).
echo "$CMD" | grep -qE '\b(pkill|pgrep|killall)\b' && deny "kill by name/pattern; kill only by a PID read from a listing"

# Secrets: site config holds the DB password and encryption key.
echo "$CMD" | grep -qE 'site_config\.json' && echo "$CMD" | grep -qE '\b(cat|less|more|head|tail|grep|rg|sed|awk|jq|cp|scp|base64|xxd|od|strings)\b' \
  && deny "reading or copying site_config.json exposes credentials"

# Restores go through byte backup + sha256, never checkout of a path.
echo "$CMD" | grep -qE 'git (checkout|restore)\s+(\S+\s+)*--\s' && deny "path restore via git; restore from the byte backup and verify by sha256"

# Sessions never hold production access.
echo "$CMD" | grep -qE '\bssh\b|\bscp\b|srv1045147|187\.124\.168\.178' && deny "production host access is human-only"

# Protected branches: develop mirrors upstream; veyqon only moves by reviewed merge.
BRANCH=$(git branch --show-current 2>/dev/null)
if echo "$CMD" | grep -qE '(^|[;&|]\s*)git (commit|merge|rebase|cherry-pick|am)\b'; then
  case "$BRANCH" in
    develop|veyqon|main|master) deny "you are on '$BRANCH'; work happens on loop/<slug> branches" ;;
  esac
fi
echo "$CMD" | grep -qE '(^|[;&|]\s*)git push\b' && deny "pushing is human-only; report the branch instead"
exit 0
