---
type: inbox
status: raw
created: 2026-09-19
---
# A person's real name can put a vendor word into model-facing text

**Problem:** The rule that model-facing text never names the platform or a vendor is absolute, but
the per-turn context block interpolates the user's own name, and a real person can legitimately be
called "Frappe Support", "Flo", or work for a company whose name is a vendor's.

## Context
Raised by the security auditor in F3's verify pass (19 Sep 2026), severity low. **Deliberately not
fixed there**, and the reasoning matters more than the finding: redacting a real person's name on a
substring match is likely worse than the problem. "flow" matches "Flowers"; "Frappe" matches a real
surname. Getting someone's name wrong in the one sentence that introduces them to the assistant is a
visible, personal failure, where the rule it would be serving exists to stop US from naming the
platform in text WE author.

## Evidence
- `flow/flow/doctype/flow_session/flow_session.py` `build_turn_context_block` interpolates
  `_display_name(get_fullname())` into the system message.
- `_display_name` collapses whitespace, replaces `"` with `'`, caps length, and drops an account id
  that is an email — but applies no vendor-word filter.
- `test_block_names_the_user_and_no_software` asserts the no-vendor-word rule only for the fixture
  name "Ada Lovelace", so it cannot catch a hostile or unlucky real name.

## Open questions
- Is the rule about text the product authors, or about every byte the model sees? If the latter, the
  same question applies to every user-authored string that reaches a prompt — attachment filenames,
  agent instructions, memory contents — and this is much bigger than the name.
- If a name must be redacted, redact to what? "an unnamed user" loses real information.
- Should there be one shared helper for "user text about to enter a prompt", rather than a rule
  re-applied by hand at each site?

## Links
[[10-specs/f3-turn-context]] · [[00-inbox/trigger-runs-name-scheduler-as-the-person]] · [[MOC]]
