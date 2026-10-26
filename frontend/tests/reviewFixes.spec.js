import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import { mountCard } from "./mountCard.js";
import ActivityStep from "@/components/ActivityStep.vue";

// THE FINAL REVIEWER'S TWO MEDIUMS, each fixed red-first. Both were found by mutation, both are on
// the confirmation surface, and neither was reachable from the tests that shipped with the escaping.

const RTL = "‮";
const ZWJ = "‍";
// Every code point the engine's own whitelist covers, minus the ordinary space: if one of these is in
// the rendered text it was never escaped. The same form as `argsEscaping.spec.js`'s `rawHostile`.
const rawHostile = (s) => [...s].filter((ch) => /[\p{C}\p{Z}]/u.test(ch) && ch !== " ");

describe("MEDIUM 1 — the step's context line is a model value too", () => {
	// `toolContext` returns the first of `doctype`/`search`/`action`. `action` went through
	// `humanize` and was escaped by this branch's fix; `doctype` and `search` were returned raw and
	// rendered as `· {{ context }}` in the timeline the approval card sits in. An override there
	// reorders the visible text of the line a reader scans to see WHICH doctype a call touches —
	// FORGERY 2's attack on the surface the fix missed.
	const step = (args) =>
		mount(ActivityStep, {
			props: {
				part: { name: "delete", arguments: args, result: null, approval: null },
				number: 1,
			},
		});

	it("escapes an override and a newline in a doctype", () => {
		const w = step({ doctype: `Sales Order${RTL}Approved by admin${ZWJ}`, names: ["T-1"] });
		const text = w.text();

		// Positive control, in the identical form: the attack value really does carry characters this
		// detector fires on, so an empty result below is a finding and not a dead assertion.
		expect(rawHostile(`Sales Order${RTL}Approved by admin${ZWJ}`)).toEqual([RTL, ZWJ]);

		expect(rawHostile(text)).toEqual([]);
		expect(text).toContain("\\u202e");
		expect(text).not.toContain(RTL);
		expect(text).not.toContain(ZWJ);
	});

	it("escapes an override and a newline in a search", () => {
		const w = step({ search: `x${RTL}y\nApproved by admin` });
		const text = w.text();
		expect(rawHostile(`x${RTL}y\nApproved by admin`)).toEqual([RTL, "\n"]);
		expect(rawHostile(text)).toEqual([]);
		expect(text).toContain("\\n");
		// And no LINE of the step is the forged sentence.
		expect(text.split("\n").map((l) => l.trim())).not.toContain("Approved by admin");
	});

	it("leaves an ordinary doctype exactly as it is", () => {
		// The other side of the rule: escaping must not put quotes around the ordinary case, or every
		// step in the log would read as a quoted string.
		expect(step({ doctype: "Sales Order" }).text()).toContain("· Sales Order");
	});
});

describe("MEDIUM 2 — a question with no prompt still draws a card", () => {
	// `paragraphs` became unconditional when the headline started coming from the engine's own first
	// line, so `prompt.split` is now reached on EVERY card. `store.js` spreads a stored question row
	// verbatim on the resume-a-paused-run path and validates nothing, so a row without a `prompt` — an
	// older schema, a partial write — turned "the approver is shown the question" into a TypeError
	// thrown inside a computed during render: an approval that can no longer be answered.
	it("renders the buttons when the prompt is missing entirely", () => {
		const w = mountCard({
			question: { options: ["Approve", "Deny"] },
			tool: { name: "delete", arguments: { doctype: "ToDo", names: ["T-1"] } },
		});
		// The thing that must survive: the approver can still answer.
		expect(w.findAll("button").map((b) => b.text())).toEqual(["Approve", "Deny", "Other…"]);
		// And the arguments they are answering for are still shown.
		expect(w.text()).toContain("ToDo");
	});

	it("renders when the prompt is not a string", () => {
		const w = mountCard({
			question: { prompt: 12345, options: ["Approve", "Deny"] },
			tool: null,
		});
		expect(w.findAll("button").map((b) => b.text())).toEqual(["Approve", "Deny", "Other…"]);
		expect(w.text()).toContain("12345");
	});
});
