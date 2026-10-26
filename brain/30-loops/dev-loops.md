---
type: loop
status: active
---
# The 7 development loops

| # | Loop | Command | Exit criteria |
|---|---|---|---|
| 1 | Capture | `/loop-capture` | Inbox note exists |
| 2 | Spec | `/loop-spec` | **A human sets `status: approved`** |
| 3 | Plan | `/loop-plan` | Human approves; ≤ 8 tasks; DO NOT CHANGE list written |
| 4 | Build | `/loop-build` | Every task: red → green → qualified → probed; `GATE=GREEN` |
| 5 | Verify | `/loop-verify` | Zero unresolved high-severity findings; `GATE=GREEN` |
| 6 | Ship | `/loop-ship` | Brain updated; push/PR commands handed to a human |
| 7 | Retro | `/loop-retro` | Retro note and ≥ 1 harness change proposed |

**Green** means `scripts/run-tests.sh` printed `GATE=GREEN` — exit 0, more than zero tests, no failures
in the output. bench's own exit code is not evidence (it exits 0 on zero tests).

**Human-only:** approving specs and plans, pushing, opening and merging PRs, editing the harness
(hooks, settings, the test gate), deploying.

[[MOC]]
