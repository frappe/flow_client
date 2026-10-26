---
description: Prepare the merge and update the brain. No ship without a brain update.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---
# Ship Loop

Branch: !`git branch --show-current`
Changes: !`git diff veyqon...HEAD --stat`

1. Write the PR description to `brain/10-specs/<slug>.md` under `## Ship`: what changed, why (spec +
   ADR links), how it was verified (GATE lines, probe results, verify table), rollback plan.
2. Spawn `brain-keeper`: spec `status: implemented` with date, MOC links, changelog line, ADR links.
3. If the plan marked the change upstream-able: list the exact engine files for an upstream branch
   cut from `develop` (no brain/, .claude/, scripts/, CLAUDE.md) and draft a conventional-commit message.
4. Commit on the loop branch.

**Pushing, opening PRs and merging are human-only.** End by printing, for the human to run:
the branch name, and the exact `git push` + `gh pr create --base veyqon` commands for it.
