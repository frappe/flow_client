import { describe, it, expect } from "vitest";
import { mountCard } from "./mountCard.js";
import ENGINE from "./fixtures/confirm_questions.json";

// THE BLAST RADIUS: every path by which a value the MODEL chose reaches the DOM on the approval
// surface, measured by rendering it.
//
// Run 13's reviewer found that S21's D0 escaping was applied to the approval question's body and to
// nothing else. `ConfirmCard` puts the engine's escaped sentence in `pre.flow-confirm-body` — and
// then hands the SAME arguments, raw, to the Details table beside it. Vue's mustache escapes HTML.
// It does not escape a newline, a bidirectional override, or a zero-width character, and
// `CodeBlock`'s `<pre>` is `white-space: pre-wrap`, so a newline in a value draws a real second line
// inside the card, above two buttons labelled Approve and Deny.
//
// This file asserts the SAFE outcome on every path, so before the fix it is the measurement (the
// paths that fail are the affected ones) and after the fix it is the guard. Every assertion is made
// on the rendered tree; nothing here reads a component's source.
//
// A path this file calls SAFE carries a positive control, per CLAUDE.md: a zero hit is a finding
// only when a positive control in the identical form hits. Each control feeds the same detector the
// same shape of hostile text and asserts the detector says YES — so "no raw override in the render"
// cannot be a detector that never fires.

const RTL = "‮"; // RIGHT-TO-LEFT OVERRIDE  — reorders the text around it, adding no character
const ZWJ = "‍"; // ZERO WIDTH JOINER       — invisible by definition
const LSEP = " "; // LINE SEPARATOR         — a line break to every layout engine
const FORGE = "Approved by admin";

// The four shapes the prompt names, in one value, so a single render exercises all of them.
const ATTACK = `T-1${RTL}${ZWJ}\n${FORGE}`;
const HUGE = "A".repeat(50000);

// ---------------------------------------------------------------------------------------------
// The detector. One function, used by every test, so "affected" and "safe" are the same question
// asked of the same code.
// ---------------------------------------------------------------------------------------------
const RAW_HOSTILE = /[\p{C}\p{Z}]/u; // C* and Z* — the engine's own whitelist in `_escaped`
const rawHostile = (text) =>
	[...String(text)]
		.filter((ch) => ch !== " " && RAW_HOSTILE.test(ch))
		.map((ch) => ch.codePointAt(0));

// The Details region of the card: the block holding the label "Details" and the arguments table.
// Located structurally, by the label a person reads, not by a utility class.
function details(w) {
	const label = [...w.element.querySelectorAll("*")].find(
		(e) => e.textContent.trim() === "Details"
	);
	expect(label, "the card has a Details block").toBeTruthy();
	return label.parentElement;
}

// What the person sees in the Details table, as one string.
const detailsText = (w) => details(w).textContent;

// A card for one gated tool call. The question body is not what this file is about, so it is the
// engine's own escaped sentence from the fixture wherever one exists and a fixed line otherwise —
// what varies between tests is the ARGUMENTS, which is the surface under test.
function card(toolName, args) {
	return mountCard({
		question: {
			prompt: `Approve \`${toolName}\`?\n\nA gated call.`,
			options: ["Approve", "Deny"],
		},
		tool: { name: toolName, arguments: args },
	});
}

// A card whose headline is the CLIENT's own label rather than the engine's first line. The card
// shows the engine's line as the headline whenever the question has a body under it
// (`titleIsEngineHead`), so a one-paragraph question is what puts `confirmTitle` on screen — which
// is the composed label these two tests are about.
function labelCard(toolName, args) {
	return mountCard({
		question: { prompt: `Approve \`${toolName}\`?`, options: ["Approve", "Deny"] },
		tool: { name: toolName, arguments: args },
	});
}

// The positive control every "this path is safe" claim carries. It proves the detector fires on the
// identical shape of text this test says is absent.
function detectorIsLive() {
	expect(
		rawHostile(ATTACK).length,
		"the detector fires on the attack value itself"
	).toBeGreaterThan(0);
	expect(rawHostile(`x${LSEP}y`), "the detector fires on U+2028").toContain(0x2028);
	expect(rawHostile("an ordinary value 42"), "and not on ordinary text").toEqual([]);
}

describe("P1 CodeBlock's <pre>, reached by a model-chosen multi-line value", () => {
	// `argKind` routes any string containing a newline to the block form, so the model decides
	// which of its values lands in a `white-space: pre-wrap` element. This is the path the defect
	// was reported on and the only one where a newline draws a REAL line.
	it("shows the newline, the override and the joiner as escapes, not as a second line", () => {
		const w = card("update", { doctype: "ToDo", note: ATTACK });
		const pre = details(w).querySelector("pre.arg-code");
		expect(pre, "a multi-line value renders as a code block").toBeTruthy();

		expect(rawHostile(pre.textContent)).toEqual([]);
		// The value is still THERE — escaped, not dropped. Escaping that deletes is a worse defect.
		expect(pre.textContent).toContain("\\n");
		expect(pre.textContent).toContain("\\u202e");
		expect(pre.textContent).toContain("\\u200d");
		detectorIsLive();
	});

	it("never lets the forged line become a line of its own", () => {
		const w = card("update", { doctype: "ToDo", note: ATTACK });
		// The claim in the reader's terms: no line of the rendered card is the forged sentence.
		const lines = detailsText(w)
			.split("\n")
			.map((l) => l.trim());
		expect(lines).not.toContain(FORGE);
		detectorIsLive();
	});

	it("caps a 50,000-character value and puts the count OUTSIDE the closing quote", () => {
		const w = card("update", { doctype: "ToDo", note: `${HUGE}\n${FORGE}` });
		const shown = details(w).querySelector("pre.arg-code").textContent;
		expect(shown.length).toBeLessThan(4000);
		// Run 12's M1: inside the quotes, a value whose own text read `… (50000 characters in all)`
		// was byte-identical to a genuinely elided one. Outside them it is the engine speaking.
		expect(shown).toMatch(/"\s*…\s*\(50018 characters in all\)/u);
		expect(shown).not.toContain(FORGE);
	});
});

describe("P2 CodeBlock's <pre>, reached by an unparseable arguments payload", () => {
	// `rawArgs` shows a payload that is not JSON verbatim rather than hiding it — which means the
	// model can put ANY bytes in this `<pre>` simply by emitting invalid JSON.
	it("escapes the raw payload it shows verbatim", () => {
		const w = card("update", `{"doctype": "ToDo", broken ${ATTACK}`);
		const pre = details(w).querySelector("pre.arg-code");
		expect(pre, "an unparseable payload is shown, not hidden").toBeTruthy();
		expect(pre.textContent).toContain("broken");
		expect(rawHostile(pre.textContent)).toEqual([]);
		detectorIsLive();
	});
});

describe("P3 ArgValue's two-column scalar cell", () => {
	it("escapes an override and a joiner in a single-line value", () => {
		const w = card("run_action", { doctype: "ToDo", action: `submit${RTL}${ZWJ}` });
		expect(rawHostile(detailsText(w))).toEqual([]);
		expect(detailsText(w)).toContain("\\u202e");
		detectorIsLive();
	});

	it("escapes a line separator, which is a line break the newline rule never sees", () => {
		// U+2028 is not "\n", so `isBlockText` does not route it to a code block: it stays in the
		// two-column cell, where every layout engine still treats it as a line break. This is the
		// gap the engine's own `_escaped` docstring records having had.
		const w = card("run_action", { doctype: "ToDo", action: `submit${LSEP}${FORGE}` });
		expect(rawHostile(detailsText(w))).toEqual([]);
		expect(detailsText(w)).toContain("\\u2028");
		detectorIsLive();
	});

	it("caps a 50,000-character single-line value", () => {
		const w = card("run_action", { doctype: "ToDo", action: HUGE });
		const text = detailsText(w);
		expect(text.length).toBeLessThan(4000);
		expect(text).toMatch(/"\s*…\s*\(50000 characters in all\)/u);
	});

	it("still shows an ordinary value as itself, with no quotes added", () => {
		// The rule this suite rests on: a value is shown VERBATIM when escaping would not change it
		// and it fits the cap. So the appearance of a quote is itself the signal that something was
		// escaped or elided — and the ordinary card does not change.
		const w = card("run_action", { doctype: "ToDo", action: "submit" });
		const text = detailsText(w);
		expect(text).toContain("submit");
		expect(text).not.toContain('"submit"');
	});
});

describe("P4 ArgValue's tuple path", () => {
	it("escapes every value inside a filter condition", () => {
		// `["in", [...]]` renders through `tupleValues` -> `formatScalar`, a second route into the
		// same cell that the scalar branch's escaping does not cover.
		const w = card("read", { doctype: "ToDo", filters: { status: ["in", ["Open", ATTACK]] } });
		expect(rawHostile(detailsText(w))).toEqual([]);
		expect(detailsText(w)).toContain("\\u202e");
		detectorIsLive();
	});

	it("shows the operator itself, and shows it as itself", () => {
		const w = card("read", { doctype: "ToDo", filters: { status: ["like", "%Open%"] } });
		expect(detailsText(w)).toContain("like");
		expect(rawHostile(detailsText(w))).toEqual([]);
		detectorIsLive();
	});
});

describe("P5 ChipList", () => {
	it("escapes the attack value the ENGINE really passes through", () => {
		// Driven by the fixture, not by a hand-made string: `delete_forged_name` is the output of the
		// real `_confirmation_question`, and its `names` list is exactly the reported attack.
		const f = ENGINE.delete_forged_name;
		const w = mountCard({ question: { prompt: f.prompt, options: f.options }, tool: f.tool });
		const chips = details(w).textContent;
		expect(rawHostile(chips)).toEqual([]);
		expect(chips).toContain("\\n");
		expect(chips).toContain("\\u202e");
		expect(chips).toContain("\\u200d");
		// And the whole card, not just the table: no line of it is the forged sentence.
		expect(w.element.textContent.split("\n").map((l) => l.trim())).not.toContain(FORGE);
		detectorIsLive();
	});
});

describe("P6 RecordsList's title", () => {
	it("escapes a record title, which is String(value) with nothing between it and the DOM", () => {
		const w = card("create", {
			doctype: "ToDo",
			records: [
				{ title: "Ordinary", n: 1 },
				{ title: ATTACK, n: 2 },
			],
		});
		expect(rawHostile(detailsText(w))).toEqual([]);
		expect(detailsText(w)).toContain("\\u202e");
		detectorIsLive();
	});

	it("caps a 50,000-character record title", () => {
		const w = card("create", {
			doctype: "ToDo",
			records: [
				{ title: "Ordinary", n: 1 },
				{ title: HUGE, n: 2 },
			],
		});
		expect(detailsText(w).length).toBeLessThan(6000);
	});
});

describe("P7 ArgValue's own recursion, one level down", () => {
	it("escapes a value nested inside an object argument", () => {
		const w = card("update", { doctype: "ToDo", values: { status: `Open${RTL}${ZWJ}` } });
		expect(rawHostile(detailsText(w))).toEqual([]);
		expect(detailsText(w)).toContain("\\u202e");
		detectorIsLive();
	});
});

describe("P8 the argument LABEL, which the model also chooses", () => {
	it("escapes a hostile key as well as a hostile value", () => {
		// `humanize(row.key)` is `String(key).replace(...)`. The keys are JSON keys from the model's
		// own tool call, so the label column is a model-controlled string like any other.
		const w = card("update", { doctype: "ToDo", [`note${RTL}${ZWJ}`]: "x" });
		expect(rawHostile(detailsText(w))).toEqual([]);
		expect(detailsText(w)).toContain("\\u202e");
		detectorIsLive();
	});

	it("caps a 50,000-character key", () => {
		const w = card("update", { doctype: "ToDo", [HUGE]: "x" });
		expect(detailsText(w).length).toBeLessThan(6000);
	});
});

describe("P9 the card's HEADLINE, which a code call writes", () => {
	it("escapes the description a code call chose for itself", () => {
		// `confirmTitle` returns `execute`'s `description` verbatim as the headline. The headline is
		// not inside `pre.flow-confirm-body`, so S21's D0 escaping never touched it.
		const w = mountCard({
			question: { prompt: "A tool's own question.", options: ["Yes", "No"] },
			tool: {
				name: "execute",
				arguments: { description: `Read only${RTL}${ZWJ}`, code: "pass" },
			},
		});
		const headline = w.element.firstElementChild.children[1].textContent;
		expect(rawHostile(headline)).toEqual([]);
		expect(headline).toContain("\\u202e");
		detectorIsLive();
	});

	it("escapes a hostile doctype and action in the headline the client composes", () => {
		const w = labelCard("run_action", {
			doctype: `ToDo${RTL}`,
			names: ["T-1"],
			action: `submit${ZWJ}`,
		});
		const headline = w.element.firstElementChild.children[1].textContent;
		// Positive control for the fixture itself: this really is the client's composed label and not
		// the engine's first line, which the engine had already escaped.
		expect(headline).toContain("Run");
		expect(headline).not.toContain("Approve");
		expect(rawHostile(headline)).toEqual([]);
		detectorIsLive();
	});

	it("leaves an ordinary headline exactly as it reads today", () => {
		// The client's own label is a translated literal with values substituted into it, and one of
		// them carries quotes of its own (`Run "{0}" on {1}`). Escaping the composed line rather than
		// the substituted values would put a backslash in front of those quotes, so this is the
		// regression that says the escaping went in the right place.
		const w = labelCard("run_action", { doctype: "ToDo", names: ["T-1"], action: "submit" });
		const headline = w.element.firstElementChild.children[1].textContent.trim();
		expect(headline).toBe('Run "Submit" on 1 ToDo');
	});
});

describe("P10 THE LEGITIMATE CASE — code the approver asked to see", () => {
	// The rule, stated so a later change cannot quietly widen it: a value renders as raw,
	// multi-line text exactly when the TOOL'S OWN DECLARATION says that argument is code —
	// `CODE_ARG_KEYS` in `toolMeta.js`, keyed by tool name and argument name, which lives in
	// reviewed client code and no model output can reach. The SHAPE of a value never earns it that
	// right: a value the model made multi-line so `isBlockText` would route it to a code block is
	// still a value the model chose, and is escaped (P1).
	it("keeps execute's code as real lines, whole, and lets the person expand it", () => {
		const f = ENGINE.execute_long_code;
		const w = mountCard({ question: { prompt: f.prompt, options: f.options }, tool: f.tool });
		const pre = details(w).querySelector("pre.arg-code");
		expect(pre).toBeTruthy();
		// Real line breaks, because this is code and code is read in lines.
		expect(pre.textContent).toContain("\n");
		expect(pre.textContent).not.toContain("\\n");
		// The preview toggle is still there and the whole code is still reachable.
		const more = [...details(w).querySelectorAll("button")].find((b) =>
			/more lines/.test(b.textContent)
		);
		expect(more, "the 4-line preview toggle survives").toBeTruthy();
	});

	it("escapes a value the MODEL made multi-line on the very same tool", () => {
		// The other side of the rule, on `execute` itself: `code` is declared, so it is raw; a second
		// multi-line argument on the same call is not declared, so it is escaped. One tool, one
		// render, both verdicts — which is what makes the rule a rule and not a special case.
		const w = card("execute", { code: "a = 1\nb = 2", note: `x\n${FORGE}` });
		const pres = [...details(w).querySelectorAll("pre.arg-code")];
		expect(pres.length).toBe(2);
		const code = pres.find((p) => p.textContent.includes("a = 1"));
		const note = pres.find((p) => p.textContent.includes("x"));
		expect(code.textContent).toContain("\n");
		expect(rawHostile(note.textContent)).toEqual([]);
		expect(note.textContent).toContain("\\n");
	});
});

describe("P11 the option BUTTONS, which a tool's own Question writes", () => {
	it("escapes an option's label and still emits the token byte for byte", async () => {
		// `optLabel` returns any option other than the two engine tokens verbatim. Options come from
		// tool code rather than from model output today, so this is the one path on the card that is
		// not yet reachable from a model reply — but a Flow Tool's own `Question` can derive them from
		// its arguments, and the card is what has to hold either way.
		//
		// The two halves are the point: the LABEL is displayed through the one rule, and the ANSWER is
		// not. What executes must never depend on how it was drawn.
		const token = `Publish${RTL}${ZWJ}`;
		const w = mountCard({
			question: { prompt: "What should happen to this draft?", options: [token, "Hold"] },
			tool: null,
		});
		const publish = w.findAll("button")[0];
		expect(rawHostile(publish.text())).toEqual([]);
		expect(publish.text()).toContain("\\u202e");

		await publish.trigger("click");
		// Emitted RAW: the person's answer is the token the engine will compare, not the drawing of it.
		expect(w.emitted("answer")[0]).toEqual([token]);
		detectorIsLive();
	});
});
