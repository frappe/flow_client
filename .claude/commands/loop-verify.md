---
description: Adversarial verification — QA, security and code review in parallel, fresh contexts
allowed-tools: Read, Bash, Grep, Glob, Agent
---
# Verify Loop

Branch: !`git branch --show-current`
Diff under review: !`git diff veyqon...HEAD --stat`

Spawn IN PARALLEL (one message, three Agent calls), each given the spec path and told to read the
diff with `git diff veyqon...HEAD`:
1. `qa-adversary` — break it.
2. `security-auditor` — attack it.
3. `code-reviewer` — correctness, tests that can actually fail, scope, upstream-mergeability.

The agent that wrote the code does not review it.

**Until all three have reported, the builder does not switch branches, edit files, or run anything that
writes to the working tree** — the reviewers are reading and testing it. Reviewers never edit files.
Test runs are serialised by the gate's lock, so a reviewer may wait for another's run; that is expected.
If a reviewer is still running after 40 minutes, message it to report what it has, and wait for that
report. Do not proceed on the other two reports alone.

Then run `scripts/run-tests.sh` yourself and include its GATE line.

Triage into one table `severity | finding | source | decision`:
- **Fix now** — every high severity, no exceptions.
- **Defer** — only with `/loop-capture`. Deferring without capturing is forgetting.
- **Dismiss** — with a written reason.

Exit: zero unresolved high-severity findings and `GATE=GREEN`. Then `/loop-ship`.
