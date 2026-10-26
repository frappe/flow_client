---
type: inbox
status: raw
created: 2026-09-19
---
# A worded refusal makes the model propose again instead of stopping

**Problem:** Answering a write confirmation with free text like "no" or "stop" is treated as a redirect:
the tool is NOT executed, but the model is told to "adjust your approach, and try again", so it
re-proposes. Only the exact "Deny" stops the run.

## Evidence
`flow/lib/agent.py:212` `_resolve_confirmation`, `:449` `_has_denial` (upstream 4a3189b, 19 Sep 2026).
Not a security issue — only the exact "Approve" executes. Conflicts with Agent Q's prompt ("If they
decline, stop"). Reachable via Flow's desk panel; our web client sends only the button strings.

## Open questions
- Recognise refusals in free text, or remove free text from confirmations entirely?
