---
description: List the seven development loops and what to run next
allowed-tools: Read, Bash, Glob
---
# The Loop System — Flow fork

Current branch: !`git branch --show-current`
Open specs: !`ls brain/10-specs/ 2>/dev/null | head -20`
Inbox: !`ls brain/00-inbox/ 2>/dev/null | grep -v gitkeep | wc -l` item(s)

Show the user this table and say which loop to run next, based on the state above.

| Loop | Command | Use when |
|---|---|---|
| 1 Capture | `/loop-capture <idea>` | Any idea, bug or request appears |
| 2 Spec | `/loop-spec <slug>` | An inbox item is worth building |
| 3 Plan | `/loop-plan <slug>` | A spec has `status: approved` (human-set) |
| 4 Build | `/loop-build <slug>` | The plan is approved |
| 5 Verify | `/loop-verify` | Build done — three fresh adversarial reviewers |
| 6 Ship | `/loop-ship` | Verify passed |
| 7 Retro | `/loop-retro` | Weekly, or after any failure |

Rules: no code without an approved spec · green only means `GATE=GREEN` from `scripts/run-tests.sh` · no merge without adversarial verification · no ship without a brain update.
