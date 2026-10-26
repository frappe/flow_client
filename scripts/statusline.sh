#!/usr/bin/env bash
# Shows: model | branch | active loop
INPUT=$(cat)
MODEL=$(echo "$INPUT" | jq -r '.model.display_name // "claude"')
BRANCH=$(git branch --show-current 2>/dev/null || echo "-")
case "$BRANCH" in
  loop/*)         LOOP="loop: ${BRANCH#loop/}" ;;
  develop|veyqon) LOOP="PROTECTED BRANCH — no loop" ;;
  *)              LOOP="no loop" ;;
esac
printf "%s | %s | %s" "$MODEL" "$BRANCH" "$LOOP"
