---
description: Implement an approved plan using the Execute/Qualify inner loop
argument-hint: <spec-slug>
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent
---
# Build Loop: $ARGUMENTS

Spec + Plan: @brain/10-specs/$ARGUMENTS.md

Preconditions: spec `status: approved` AND a `## Plan` section. If not, stop.

## Setup
1. `git switch -c loop/$ARGUMENTS veyqon` (or confirm you are already on it).
2. Baseline: `scripts/run-tests.sh`. Record TESTS_RUN. If not `GATE=GREEN`, STOP — you cannot tell
   your breakage from a pre-existing one.
3. Byte-backup every file in the plan to `/tmp/$ARGUMENTS-backup/` with recorded sha256.

## For EVERY task — do not batch
1. **Test first**, from the acceptance criterion. Run it: `scripts/run-tests.sh <module>`. It must be
   RED for the right reason. Paste the failure line.
2. **Implement.** Smallest change that satisfies the criterion.
3. **Green:** `scripts/run-tests.sh <module>` → `GATE=GREEN`.
4. **Qualify:** re-read the written criterion (not your memory of it). Edge cases, not just the happy path.
5. **Probe:** break the implementation on purpose, watch the task's test go red, restore from your
   backup copy of the FINAL version, verify by sha256. Never `git checkout --`.
6. Gap? Fix it now and re-qualify. Only then flip that entry's `passes` in `features.json`.

## Exit
Full suite: `MIN_TESTS=<baseline + new> scripts/run-tests.sh` → `GATE=GREEN`. Diff confined to planned
files (`git diff --stat veyqon...HEAD`). Commit on the loop branch. Do not push.
Tell the user to run `/loop-verify`. Do not self-approve.
