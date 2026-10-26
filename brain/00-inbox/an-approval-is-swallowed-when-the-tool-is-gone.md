---
type: inbox
status: resolved
created: 2026-09-20
---
# An approval is swallowed when the tool is gone

Found by run 4's ADR-003 evidence spike, not by a report — which is why it is written down after
the fix rather than before it.

A person answers an approval question. By the time the run resumes, the tool is no longer in the
runtime (removed, renamed or disabled while the run was paused). Nothing executes, nothing is
denied, and the string the person typed is recorded as that tool call's result. The model reads its
own tool call as having returned "Approve" and may report the action done.

Resolved by [[10-specs/s15-resume-fails-closed]], which also closes the mirror case found during
its verify pass: a tool given a confirmation requirement while paused would otherwise execute on an
answer to a question it asked itself.

Still open, and named in that spec's Open questions: a tool REPLACED under the same name still
executes on the old approval.
