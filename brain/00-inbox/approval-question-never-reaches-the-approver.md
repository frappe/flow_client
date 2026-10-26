---
type: inbox
status: raw
created: 2026-09-19
---
# The approval question's text never reaches the person approving

Two independent reviewers (qa-adversary and security-auditor, E5 v2 verify, 2026-09-19) found the
same thing by reading the shipped client, not by guessing.

`frontend/src/components/AssistantMessage.vue:65` always passes `:tool="item.part"` to
`ConfirmCard` for a tool confirmation. `frontend/src/components/ConfirmCard.vue:20-26` then does:

    const title = computed(() => confirm.value ? confirm.value.title : props.question.prompt.split("\n\n")[0].trim());
    const body  = computed(() => props.tool ? "" : props.question.prompt.split("\n\n").slice(1).join("\n\n").trim());

With `tool` non-null, `body` is `""` and `title` comes from the client's own `confirmTitle()`, which
humanises the SLUG. `grep -rn "\.prompt" frontend/src` returns only those two lines, so
`question.prompt` is rendered ONLY for free-text asks.

**Consequence: E5 (both v1 and v2) is engine-only in the bundled client.** The plain-language
sentence and the human title are computed, stored on the run and sent over the API, and never
displayed. Any consumer of `payload["questions"]` (`flow/api/api.py:222`, `:279`) does see them.

Not a defect introduced by E5 v2 — it was equally true of v1 and was not noticed in run 1.

**Why it was not fixed in unattended run 2:** the fix is a client change outside the spec's file
list, and it needs a decision nobody but the owner can make — the card already shows the arguments
through `ArgsView`, so simply pasting the prompt body in would show them twice. What the card should
display (sentence only? sentence in place of the humanised slug? title from the record?) is a product
choice.

Relates to [[10-specs/e5-confirm-prompt-field-v2]].
