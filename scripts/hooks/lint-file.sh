#!/usr/bin/env bash
# PostToolUse:Edit|Write — format/lint the file just written, using UPSTREAM's own pre-commit
# config and pinned tool versions. Never a formatter with defaults: upstream is tab-indented and
# its doctype JSON is 1-space with no final newline; default ruff/prettier would rewrite whole
# files and make every upstream merge a conflict. (Scaffold version ran prettier on *.json.)
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
[ -z "$FILE" ] && exit 0
[ -f "$FILE" ] || exit 0

case "$FILE" in
  */flow/*.py|flow/*.py|*/flow/*.js|flow/*.js|*/flow/*.vue|flow/*.vue)
    if command -v pre-commit >/dev/null; then
      pre-commit run --files "$FILE" >/dev/null 2>&1 || true
      # A second run reports what the first could not auto-fix.
      if ! OUT=$(pre-commit run --files "$FILE" 2>&1); then
        echo "LINT: pre-commit still reports problems in $FILE:" >&2
        echo "$OUT" | grep -vE '^\s*$|Passed|Skipped' | head -20 >&2
      fi
    else
      echo "LINT SKIPPED: pre-commit not installed — run scripts/doctor.sh" >&2
    fi
    ;;
esac
exit 0
