---
type: adr
status: accepted
created: 2026-09-19
---
# ADR-001: Fork frappe/flow_client as VEYQON/flow

## Context
Agent Q runs on Frappe's Flow engine. Changes we need (per-turn context, streaming persistence,
business-language confirmations) live inside the engine and cannot be made from our own apps.
Production's `apps/flow` has no git metadata; on 18 Sep 2026 it was measured byte-identical to upstream
`4a3189b` after CRLF→LF normalisation (185/185 files; the only extras were 86 `__pycache__` files).

## Decision
- Fork `frappe/flow_client` → `VEYQON/flow`, starting at `4a3189b`
  (anchor hash `1d3780090f2162a6aaf904b8f1f75e8c98b307487f1a307496622b754096c5dc`, computed on two machines).
- `develop` mirrors upstream exactly; `veyqon` carries our changes and this harness; work happens on
  `loop/<slug>`; upstream contributions are cut from `develop` with engine code only.
- The fork is LF (`.gitattributes`: `* text=auto eol=lf`). We do not reproduce production's CRLF.
- Offer every generally useful change upstream, to keep the fork's diff small.

## Alternatives considered
- **Patch production in place** — rejected: unversioned, and how the current tree got there is already unrecorded.
- **Work only from our own apps (tools, prompts)** — rejected for engine-level needs: e.g. the date can only
  reach the model reliably from inside the message builder.
- **No fork, upstream-only** — rejected as the only path: our timeline can't depend on upstream review.

## Consequences
- We own merge cost on every upstream release; kept low by the branch model and upstreaming.
- The licence (root `license.txt` AGPL-3.0, `pyproject.toml` AGPL-3.0-or-later) needs a lawyer's reading
  before the fork serves production.
- The first deploy replaces a CRLF tree with LF: every file changes. That deploy must carry no code change,
  and the tree-hash gate must normalise line endings and ignore `__pycache__`.

---
ADRs are immutable. To change this decision, write a new ADR that supersedes it.
