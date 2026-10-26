#!/usr/bin/env bash
# Run the scenarios inside a platform context, which is what `_()` in the engine needs.
#
# The runner itself is plain Python and makes no request of its own; this only supplies the
# import context the engine expects. Arguments pass straight through:
#   evals/run.sh                                  all scenarios
#   evals/run.sh --scenario deny_stops_the_batch
#   evals/run.sh --list                           (prints names; there is no verdict to give)
#
# It does NOT trust the wrapped command's exit code — that lesson is in CLAUDE.md and it applies
# here for the same reason. The verdict is read out of the runner's own summary line, and a missing
# summary is a failure, not a pass.
set -uo pipefail

BENCH="${FLOW_BENCH:-$HOME/code/flow-bench}"
SITE="${FLOW_SITE:-flow.localhost}"
EVALS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ -d "$BENCH/sites" ] || { echo "no bench at $BENCH (set FLOW_BENCH)" >&2; exit 2; }

ARGS="$(printf '%s\n' "$@" | python3 -c 'import json,sys; print(json.dumps([l for l in sys.stdin.read().splitlines() if l]))')"

OUT="$(cd "$BENCH" && printf '%s\n' "
import sys
sys.path.insert(0, '$EVALS')
import run
run.main($ARGS)
" | bench --site "$SITE" console 2>&1)"

# The console prefixes the first line of output with its own prompt; strip it, then print the
# runner's table and nothing else.
echo "$OUT" | sed -E 's/^In \[[0-9]+\]: //' | sed -n '/^SCENARIO/,/^EVALS=/p'

SUMMARY="$(echo "$OUT" | grep -oE 'EVALS=[0-9]+ PASSED=[0-9]+ FAILED=[0-9]+ KNOWN_DEFECT=[0-9]+ FIXED=[0-9]+' | tail -1)"
if [ -z "$SUMMARY" ]; then
	echo "EVALS_GATE=RED reason=no-summary-line"
	exit 1
fi

# KNOWN_DEFECT is deliberately NOT part of the verdict. Those scenarios describe things this
# project has proven are wrong and has not fixed; they are written down, so they are not news, and
# letting them hold the gate red forever would make it stop being read. They are still printed,
# with the reason, every single run.
#
# FIXED IS part of the verdict. A known defect that has started passing means the code was fixed
# and the record was not — the suite is now asserting something untrue about the system, and only
# a person can correct that.
case "$SUMMARY" in
	*"FAILED=0 "*"FIXED=0") echo "EVALS_GATE=GREEN"; exit 0 ;;
esac
echo "EVALS_GATE=RED reason=${SUMMARY// /,}"
exit 1
