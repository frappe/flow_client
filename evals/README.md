# Evaluations

A scenario runner for the agent loop. It runs entirely in this process against a scripted model.

## What these evaluate, and what they do not

**They test the plumbing, not the judgement.** A scenario says: given this model output, does the
engine call the right tool, ask for approval when it should, execute only on the exact "Approve",
and never tell the person something is done while it is not. Every one of those is a property of
the engine, and a scripted model is the right instrument for it — it makes the answers
deterministic and the failures unambiguous.

**They say nothing about whether a real model would choose well.** Whether the assistant picks the
right tool, phrases an approval sensibly, or refuses when it should is a question about the model,
and none of it is measured here. Real-model evaluations need credentials and a budget decision from
the owner. They are not part of this, and nothing here should be quoted as evidence about model
quality.

## Running them

    evals/run.sh                                  # all scenarios
    evals/run.sh --scenario deny_stops_the_batch
    evals/run.sh --list

The wrapper exists for one reason: the engine calls the platform's translation helper when it
builds an approval question, and that needs a platform context. `run.py` itself is plain Python and
makes no request of its own; the wrapper only supplies the import context. Set `FLOW_BENCH` and
`FLOW_SITE` if yours are not the defaults.

**The verdict is the last line, `EVALS_GATE=GREEN` or `EVALS_GATE=RED reason=…`.** The wrapper does
not trust the wrapped command's exit code — that lesson is in `CLAUDE.md` and it applies here for
exactly the same reason — so it reads the runner's own summary line instead, and treats a missing
summary as a failure rather than a pass.

`python3 evals/run.py` works directly too, if you already have a context.

## `deny_stops_the_batch` is RED on `veyqon`, and that is correct

Four of the five scenarios pass on `veyqon`. `deny_stops_the_batch` asserts that a Deny beside an
Approve executes neither, which is [[../brain/10-specs/s14-deny-stops-batch|S14]]'s behaviour and
is not on `veyqon`:

    deny_stops_the_batch  FAIL
      - [approve_and_deny] expected [] to run, saw ['send_money']
      - [deny_and_approve] expected [] to run, saw ['delete_records']

The suite reproduced that defect independently on its first run, which is the most useful thing it
has done so far. It turns green when S14 merges, and it is worth keeping red until then rather than
weakening it: a scenario that describes what should happen is more useful than one that describes
what does.

## No network, no credentials, no real model

The runner builds a code `Agent` around a scripted model defined in `run.py`. It never constructs
the platform's `Model` class, never reads a credential, and never makes a request.

`assert_no_real_model()` runs before any scenario and **refuses to start** if the environment looks
like a real model is configured — any known provider credential variable, or the explicit
`FLOW_EVALS_ALLOW_REAL` escape hatch being set. That refusal is a hard error, not a warning, and
`tests/test_runner.py` proves it fires.

It does not read `sites/*/site_config.json`, and it must never be changed to.

## Tests

The runner has its own tests, outside the bench's test gate because nothing under `flow/` changes:

    python3 -m unittest discover -s evals/tests -t .

## Writing a scenario

One YAML file per scenario in `scenarios/`. The fields:

| field | meaning |
|---|---|
| `name` | unique slug; matches the filename |
| `description` | one line, for the table |
| `user_message` | what the person says |
| `agent.instructions` | the agent's instructions |
| `tools` | each `{name, description, parameters, requires_confirmation}`; every tool is a stub that records its call and returns `result` |
| `model_script` | the scripted turns, in order: each is `{tool_calls: [{name, arguments, id}]}` or `{content: "..."}` |
| `expect.tool_calls` | the tool calls the engine should make, in order, as `{name, arguments}`; `arguments` may be a subset |
| `expect.pauses` | whether the run should pause for approval |
| `expect.questions` | for a pause: how many, and the options each must carry |
| `expect.after` | a map of answer-set name → `{answers, executed, output, status}`; `executed` is the tools that must have actually run |
| `expect.absent_text` | text that must NOT appear anywhere the person or the model sees — vendor names, "done" while something is pending |

`expect.after` is where the approval contract is actually checked: a scenario names what happens
after "Approve", after "Deny", and after free text, and the runner asserts on what executed rather
than on what the run said.

## Scenarios that are expected to fail

Some scenarios describe a defect this project has **proven** and has **not fixed**. They assert the
behaviour that *should* happen and are expected to fail until someone claims the defect with a
spec. Such a scenario carries a `known_defect:` key whose value says what the defect is and where
it is written down:

```yaml
known_defect: >-
  Reproduces today, on veyqon and on develop. ... Captured at brain/00-inbox/<slug>.md;
  no spec has claimed it yet.
```

A bare `known_defect: true` is **refused**. A known defect that does not say what it is is
indistinguishable from a scenario somebody silenced.

There are four outcomes, not two, and the summary line counts all of them:

| verdict | meaning | holds the gate red? |
|---|---|---|
| `PASS` | asserted behaviour happened | no |
| `FAIL` | asserted behaviour did not happen | **yes** |
| `KNOWN-DEFECT` | a marked scenario failed, as recorded | **no** — it is already written down, and a permanently red suite stops being read |
| `FIXED` | **a marked scenario PASSED** | **yes** — the code was fixed and the record was not, so the suite is now asserting something untrue. Delete the `known_defect` key |

`FIXED` is the outcome that earns the machinery. It is the only one of the four whose fix is to
edit a scenario rather than the engine.

**Never turn a failing scenario into a passing one by rewriting it to assert the defect.** That
produces a pin on broken behaviour that nobody will ever read as a problem. Mark it and say why.

## Two scenarios that assert about the engine's own tools

Most scenarios here invent their tools, which is right for testing the loop: the loop does not care
what a tool does. Two do not, and they use a `builtin:` key that takes a tool's **shipped surface** —
whether it is gated, and the approval question it raises — from the registry itself, while the body
stays a recording stub so nothing is written.

That distinction is the point. A suite of invented tools can never notice that a shipped tool's
approval was turned off, or that its question stopped saying what it authorises. These two can:

- `keeping_a_note_is_approved_first` — the tool for keeping notes asks first, and the question shows
  the exact wording that would be kept.
- `an_approved_execute_shows_its_code` — the code-running tool's question shows the code in full.
  It has to: that tool's sandbox holds the write tools unwrapped, so nothing inside it is asked
  about again and the question is the only place a person sees what will happen. **The code IS the
  approval.**

## One scenario asserts a defect nobody has claimed

`auto_approve_turns_every_gate_off` is a `known_defect`: one flag on a trigger record skips the
confirmation branch for every tool at once, so an unattended run performs every gated write with
nobody asked. It is deliberate and documented — an unattended run has nobody to answer a question —
and it still means the whole approval mechanism has a single switch. It is reported, with its
reason, on every run, and it holds nothing red until a spec claims it.

