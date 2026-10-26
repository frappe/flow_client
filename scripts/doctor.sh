#!/usr/bin/env bash
# doctor.sh — prove the harness is wired up AND that every guard can actually say no.
# A hook that cannot execute (missing jq, not executable, wrong path) does not stop Claude and
# does not warn you. Run after every setup and after every change to .claude/ or scripts/.
#   scripts/doctor.sh      (from the repo root)
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
PASS=0; FAIL=0
ok()  { printf "  PASS  %s\n" "$1"; PASS=$((PASS+1)); }
bad() { printf "  FAIL  %s\n        -> %s\n" "$1" "$2"; FAIL=$((FAIL+1)); }

# expect <exit-code> <description> <hook> <json>
expect() {
  local want="$1" desc="$2" hook="$3" json="$4" rc
  echo "$json" | bash "scripts/hooks/$hook.sh" >/dev/null 2>&1; rc=$?
  [ "$rc" -eq "$want" ] && ok "$desc (exit $rc)" || bad "$desc — got exit $rc, want $want" "The guard is decorative until this passes."
}

echo "-- Environment"
for t in jq git bash bench pre-commit claude; do
  command -v "$t" >/dev/null && ok "$t on PATH" || bad "$t missing" "see brain/70-runbooks/local-setup.md"
done
git rev-parse --is-inside-work-tree >/dev/null 2>&1 && ok "inside a git repo" || bad "not a git repo" "run from the fork root"
[ -d "$HOME/code/flow-bench/apps/frappe" ] && ok "bench present at ~/code/flow-bench" || bad "bench directory ~/code/flow-bench missing" "brain/70-runbooks/local-setup.md"
[ "$(readlink -f "$HOME/code/flow-bench/apps/flow" 2>/dev/null)" = "$(git rev-parse --show-toplevel 2>/dev/null)" ] \
  && ok "bench apps/flow is a symlink to THIS repo" || bad "bench apps/flow does not point here" "edits here would not be what the tests run"

echo "-- Harness files"
for f in CLAUDE.md features.json .claude/settings.json brain/MOC.md scripts/run-tests.sh; do
  [ -f "$f" ] && ok "$f exists" || bad "$f missing" "re-copy the harness"
done
for h in scripts/hooks/*.sh scripts/run-tests.sh scripts/statusline.sh; do
  [ -x "$h" ] && ok "$h executable" || bad "$h not executable" "chmod +x scripts/*.sh scripts/hooks/*.sh"
done
jq -e . .claude/settings.json >/dev/null 2>&1 && ok "settings.json is valid JSON" || bad "settings.json invalid" "Claude ignores a malformed settings file silently"

echo "-- Guards say NO (each must block)"
expect 2 "guard-bash blocks rm -rf /"            guard-bash '{"tool_input":{"command":"rm -rf /"}}'
expect 2 "guard-bash blocks pkill -f"            guard-bash '{"tool_input":{"command":"pkill -f bench"}}'
expect 2 "guard-bash blocks cat site_config"     guard-bash '{"tool_input":{"command":"cat sites/flow.localhost/site_config.json"}}'
expect 2 "guard-bash blocks git checkout -- f"   guard-bash '{"tool_input":{"command":"git checkout -- flow/lib/agent.py"}}'
expect 2 "guard-bash blocks git push"            guard-bash '{"tool_input":{"command":"git push origin loop/x"}}'
expect 2 "guard-bash blocks ssh to production"   guard-bash '{"tool_input":{"command":"ssh veyqon@srv1045147.hstgr.cloud"}}'
expect 2 "guard-protected blocks editing the test gate" guard-protected '{"tool_input":{"file_path":"scripts/run-tests.sh","content":"exit 0"}}'
if [ -f features.json ]; then
  expect 2 "guard-protected blocks rewording features.json" guard-protected \
    '{"tool_input":{"file_path":"features.json","content":"{\"features\":[{\"id\":1,\"description\":\"lol whatever\",\"passes\":true}]}"}}'
fi

echo "-- Guards say YES (over-blocking gets a guard switched off)"
expect 0 "guard-bash allows ls -la"               guard-bash '{"tool_input":{"command":"ls -la"}}'
expect 0 "guard-bash allows the test gate"        guard-bash '{"tool_input":{"command":"scripts/run-tests.sh flow.tests.test_session"}}'
expect 0 "guard-protected allows editing engine code" guard-protected '{"tool_input":{"file_path":"flow/lib/agent.py","content":"x"}}'

echo "-- Branch"
B=$(git branch --show-current 2>/dev/null)
case "$B" in
  develop|veyqon) printf "  WARN  on protected branch '%s' — start work with: git switch -c loop/SPEC-SLUG veyqon\n" "$B" ;;
  *) ok "on '$B'" ;;
esac

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] && echo "DOCTOR=GREEN" || echo "DOCTOR=RED"
[ "$FAIL" -eq 0 ]
