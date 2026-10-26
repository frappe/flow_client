---
description: Turn an approved spec into a file-level implementation plan
argument-hint: <spec-slug>
allowed-tools: Read, Edit, Glob, Grep, Bash, Agent
---
# Plan Loop: $ARGUMENTS

Spec: @brain/10-specs/$ARGUMENTS.md

Precondition: frontmatter `status: approved`. If not, stop.

1. Read the spec and the code it touches. Find every call site and dependency with grep; every
   "nothing else uses this" claim carries a positive control in the identical command form.
2. Produce an ordered task list. Each task: files to create/modify, the test that proves it, the
   acceptance criterion it satisfies.
3. Record a **DO NOT CHANGE** list: files and functions this work must not touch (always includes the
   write-confirmation functions in `flow/lib/agent.py` unless the spec names them).
4. Rollback plan, and whether the change is upstream-able as-is.
5. Append it all under `## Plan` in the spec.

More than 8 tasks → stop and split the spec. A task that satisfies no criterion is scope creep.
No implementation code in this loop. Present the plan and **STOP for human approval.**
