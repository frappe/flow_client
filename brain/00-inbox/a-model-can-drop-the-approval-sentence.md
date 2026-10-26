---
type: inbox
status: raw
created: 2026-09-19
---
# A model can make the administrator's approval sentence disappear

Found by security-auditor during E5 v2 verify, 2026-09-19, and demonstrated by running it.

E5 v2 abandons the whole sentence — falling back to the bare JSON arguments — whenever a
substituted value is not a single value or is over 200 characters. The model chooses the argument
values, so **the model chooses whether the sentence appears at all**. Measured, with the template
`"PERMANENTLY DELETE every invoice for {customer}. This cannot be undone."`:

    normal string   warning shown: True
    list            warning shown: False
    None            warning shown: False
    object          warning shown: False
    201 chars       warning shown: False

A model that wants a dangerous call to look routine passes `["Acme"]` instead of `"Acme"` and the
operator gets upstream's bare dump with no signal that a warning was written and dropped.

**Mitigating:** the exact arguments are still shown, so nothing FALSE is ever stated, and the result
is no worse than the behaviour before E5 existed. **Not mitigating:** it defeats the feature exactly
when the feature matters most.

**Why it was not fixed in unattended run 2:** the fallback-to-JSON behaviour is part of the v2 design
the owner fixed in writing ("It never shows a partial or a shortened value"), and the run's brief
said not to substitute my own design. The two candidate fixes both change it: render a non-scalar as
an explicit marker (`[a list of 1 value — see below]`) instead of abandoning, or keep the drop and
prepend a fixed, non-substituted line saying the wording could not be filled in. The second is
probably right — a silent fallback is the problem, not the fallback.

Relates to [[10-specs/e5-confirm-prompt-field-v2]].
