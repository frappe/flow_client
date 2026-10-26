---
type: inbox
status: raw
created: 2026-09-19
---
# A dropped connection during streaming loses the run's output

**Problem:** `flow_run.py:172` `stream_with_persistence` persists only on `Done`. A client disconnect
ends the generator; the run is marked failed and the partial output is not saved.

## Evidence
Read in upstream 4a3189b, 18 Sep 2026.

## Open questions
- Persist incrementally, or finish the run server-side after the client leaves?
