#!/usr/bin/env bash
# Stop — if engine code changed but the brain didn't, say so. Advisory (exit 0).
# Scaffold version matched ^(apps|services)/ — paths that do not exist in this repo, so it could
# never fire. Engine code lives under flow/.
CODE=$(git diff --name-only HEAD 2>/dev/null | grep -cE '^flow/')
BRAIN=$(git diff --name-only HEAD 2>/dev/null | grep -cE '^brain/')
if [ "$CODE" -gt 0 ] && [ "$BRAIN" -eq 0 ]; then
  echo "REMINDER: $CODE engine file(s) changed but the brain was not updated." >&2
  echo "Update the spec's status/notes in brain/10-specs/. /loop-ship does this properly." >&2
fi
exit 0
