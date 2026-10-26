#!/usr/bin/env bash
# run-tests.sh — the ONLY accepted definition of "green" for the Flow fork.
#
# Why this exists (measured 19 Sep 2026, Frappe v16.31.0; lock added 19 Sep 2026 after concurrent-run deadlocks):
#   - `bench init` exited 0 after failing and rolling back.
#   - `bench run-tests` exits 0 when it discovers ZERO tests (frappe/commands/testing.py:171,
#     `all(...)` over an empty list is True). A typo in --module is a silent green.
# So green requires ALL of: exit 0, at least one test run, no FAILED/ERROR in the output,
# and (optionally) at least MIN_TESTS tests.
#
# Usage:
#   scripts/run-tests.sh                              # whole app
#   scripts/run-tests.sh flow.tests.test_session      # one module
#   MIN_TESTS=180 scripts/run-tests.sh                # also fail if fewer tests ran
# Env: BENCH_DIR (default ~/code/flow-bench), SITE (default flow.localhost)

set -uo pipefail
BENCH_DIR="${BENCH_DIR:-$HOME/code/flow-bench}"
SITE="${SITE:-flow.localhost}"
MODULE="${1:-}"
export PATH="$HOME/.local/bin:$PATH"

LOG_DIR="$BENCH_DIR/logs/run-tests"
mkdir -p "$LOG_DIR" || { echo "GATE=RED reason=cannot-create-log-dir"; exit 1; }
LOG="$LOG_DIR/$(date +%Y%m%dT%H%M%S)${MODULE:+-$MODULE}.log"

cd "$BENCH_DIR" || { echo "GATE=RED reason=no-bench-dir:$BENCH_DIR"; exit 1; }

# One test run at a time. All runs share one site database; concurrent runs deadlock in MariaDB and
# produce ERROR lines that are not real failures (measured 19 Sep 2026, run 1 of the unattended loop).
command -v flock >/dev/null || { echo "GATE=RED reason=flock-missing"; exit 1; }
exec 9>"$BENCH_DIR/.run-tests.lock"
LOCK_T0=$(date +%s)
flock -w "${LOCK_WAIT_SECONDS:-2400}" 9 || { echo "GATE=RED reason=lock-timeout-after-${LOCK_WAIT_SECONDS:-2400}s"; exit 1; }
echo "LOCK_WAITED_SECONDS=$(( $(date +%s) - LOCK_T0 ))"

if [ -n "$MODULE" ]; then
  bench --site "$SITE" run-tests --app flow --module "$MODULE" > "$LOG" 2>&1
else
  bench --site "$SITE" run-tests --app flow > "$LOG" 2>&1
fi
RC=$?

# The panel's own suite. `GATE=GREEN` said nothing about frontend/ until this ran (run 13).
# Skipped, loudly, when node_modules is absent - a silent skip is how a suite stops running.
JS_RC=0
if [ -d "$HOME/code/veyqon-flow/node_modules/vitest" ]; then
  ( cd "$HOME/code/veyqon-flow" && yarn --silent test ) > "$LOG.js" 2>&1
  JS_RC=$?
  echo "JS_TESTS=$(grep -oE 'Tests +[0-9]+ passed' "$LOG.js" | grep -oE '[0-9]+' | tail -1) JS_EXIT=$JS_RC JS_LOG=$LOG.js"
  [ "$JS_RC" -ne 0 ] && tail -30 "$LOG.js"
else
  echo "JS_TESTS=SKIPPED reason=no-node_modules (run: cd ~/code/veyqon-flow && yarn install --frozen-lockfile)"
  JS_RC=1
fi

RAN=$(grep -Eo '^Ran [0-9]+ tests?' "$LOG" | awk '{s+=$2} END{print s+0}')
FAILED_LINES=$(grep -Ec '^FAILED \(|^ (ERROR|FAIL) ' "$LOG")

echo "LOG=$LOG"
echo "EXIT=$RC TESTS_RUN=$RAN FAILURE_LINES=$FAILED_LINES"
tail -15 "$LOG"

REASON=""
[ "$RC" -ne 0 ] && REASON="${REASON}exit-$RC,"
[ "$RAN" -eq 0 ] && REASON="${REASON}zero-tests-ran,"
[ "$FAILED_LINES" -gt 0 ] && REASON="${REASON}failures-in-output,"
[ "$JS_RC" -ne 0 ] && REASON="${REASON}js-suite-failed,"
if [ -n "${MIN_TESTS:-}" ] && [ "$RAN" -lt "$MIN_TESTS" ]; then
  REASON="${REASON}fewer-than-MIN_TESTS($RAN<$MIN_TESTS),"
fi

if [ -z "$REASON" ]; then
  echo "GATE=GREEN"
  exit 0
fi
echo "GATE=RED reason=${REASON%,}"
exit 1
