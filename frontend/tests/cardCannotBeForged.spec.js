import { describe, it, expect } from "vitest";
import { mountCard } from "./mountCard.js";

// FOUR FORGERIES, one test each, every assertion on the rendered DOM.
//
// The approval card is the one surface in the product whose whole job is to be trustworthy: two
// buttons, and above them the only account of what pressing Approve will do. A forgery here is not a
// cosmetic bug — it is a person authorising something other than what they read.
//
// Each test asserts THE ESCAPE, NOT THE EFFECT. That distinction is the whole file: "the card does
// not look wrong" is unfalsifiable in jsdom, which has no layout engine and no bidi algorithm, so
// every test here asserts that the dangerous character is not in the DOM and that its escape is —
// which is a fact jsdom can and does answer.
//
// The mutation each one is probed with is named in its own comment, and the probe results are in the
// run log with a sha256 pair per mutation.

const RTL = "‮"; // RIGHT-TO-LEFT OVERRIDE
const ZWJ = "‍"; // ZERO WIDTH JOINER

// Everything a person reads on the card, as one string.
const seen = (w) => w.element.textContent;
// The lines a person reads, which is what "a forged line" means.
const lines = (w) =>
	seen(w)
		.split("\n")
		.map((l) => l.trim());
// Unescaped quotes are the panel's own boundary marks: `escapeForDisplay` maps `"` to `\"`, so a
// value cannot produce one. Counting them is how a reader tells the panel's words from the value's.
const unescapedQuotes = (text) => (text.match(/(^|[^\\])"/g) || []).length;

function card(toolName, args) {
	return mountCard({
		question: {
			prompt: `Approve \`${toolName}\`?\n\nA gated call.`,
			options: ["Approve", "Deny"],
		},
		tool: { name: toolName, arguments: args },
	});
}

describe("FORGERY 1 — a newline and a line of authority under it", () => {
	// Probe: delete the `displayText` call from `CodeBlock.vue`'s `text` computed.
	it("never draws the line 'Approved by admin' that no engine ever wrote", () => {
		const w = card("delete", { doctype: "ToDo", note: "T-1\nApproved by admin" });

		// The forged sentence is not a line of the card.
		expect(lines(w)).not.toContain("Approved by admin");
		// It is not absent because it was dropped — it is present, as one line, with its newline shown.
		expect(seen(w)).toContain("T-1\\nApproved by admin");
		// The escape, not the effect: no raw newline came from the value. The card's own markup
		// contains newlines, so the claim is made about the cell that holds the value.
		const pre = w.element.querySelector("pre.arg-code");
		expect(pre.textContent).not.toContain("\n");
		expect(pre.textContent).toContain("\\n");

		// Positive control: the detector would have fired. The raw value really does contain a
		// newline followed by exactly that sentence, so a green here is about the escaping.
		expect("T-1\nApproved by admin".split("\n")[1]).toBe("Approved by admin");
	});
});

describe("FORGERY 2 — an override that reverses the sense of the sentence", () => {
	// Probe: delete the `displayText` call from `formatScalar` in `lib/toolMeta.js`.
	it("shows a right-to-left override as an escape, so 'read only' cannot read as 'and write'", () => {
		// Stored: `Read only` + OVERRIDE + `etirw dna`. Rendered with the override obeyed, a bidi
		// engine draws the tail right-to-left and a person reads "Read only and write".
		const value = `Read only${RTL}etirw dna`;
		const w = card("run_action", { doctype: "ToDo", names: ["T-1"], action: value });
		const text = seen(w);

		expect(text).not.toContain(RTL);
		expect(text).toContain("\\u202e");
		// And the characters are in the order they were stored, so what is drawn is what is held.
		expect(text).toContain("Read only\\u202eetirw dna");

		// Positive control: the value really carries U+202E, i.e. the hazard is real and the test is
		// not asserting the absence of a character that was never there.
		expect(value.codePointAt(9)).toBe(0x202e);
	});
});

describe("FORGERY 3 — a joiner splitting the word the approver would search for", () => {
	// Probe: delete the `displayText` call from `RecordsList.vue`'s title.
	it("shows a zero-width joiner, so a word that READS whole is not silently unsearchable", () => {
		// `de<ZWJ>lete` renders as the word "delete" to the eye and is not the string "delete" to
		// anything that searches — a find-in-page, a copy into a ticket, a reviewer's grep.
		const split = `de${ZWJ}lete`;
		const w = card("create", {
			doctype: "ToDo",
			records: [
				{ title: "Ordinary", n: 1 },
				{ title: `${split} everything`, n: 2 },
			],
		});
		const text = seen(w);

		expect(text).not.toContain(ZWJ);
		expect(text).toContain("\\u200d");
		// The reader is shown the break rather than a word with an invisible seam in it.
		expect(text).toContain("de\\u200dlete everything");

		// Positive control, and the reason this forgery matters: the raw value LOOKS like "delete"
		// and does not CONTAIN it. Both halves asserted, so neither is assumed.
		expect(split).not.toContain("delete");
		expect([...split].filter((c) => c !== ZWJ).join("")).toBe("delete");
	});
});

describe("FORGERY 4 — a value that ends in what looks like the card's own words", () => {
	// Probe: delete the `displayText` call from `CodeBlock.vue`'s `text` computed (the quote boundary
	// is what this test is really about, and that is where the quoting happens for a block value).
	it("cannot fake the panel's elision count, because the count sits outside a quote no value can write", () => {
		// Run 12's M1, attempted from the other side: a value whose own text IS an elision notice. If
		// the count were inside the quotes, this value and a genuinely elided 50 000-character one
		// would be byte-identical on screen.
		const forged = `T-1" … (3 characters in all)`;
		const w = card("delete", { doctype: "ToDo", note: `${forged}\nmore` });
		const pre = w.element.querySelector("pre.arg-code");
		const shown = pre.textContent;

		// The value's own quote is escaped, so it is not a boundary.
		expect(shown).toContain('T-1\\"');
		// Exactly one pair of unescaped quotes: the pair the panel wrote. Anything after the closing
		// one is the panel speaking, and there is nothing after it here because nothing was elided.
		expect(unescapedQuotes(shown)).toBe(2);
		expect(shown.trimEnd().endsWith('"')).toBe(true);

		// Positive control on the boundary claim: a genuinely elided value DOES put a count after the
		// closing quote, so the assertion above distinguishes the two cases rather than always holding.
		const huge = card("delete", { doctype: "ToDo", note: "A".repeat(50000) + "\nmore" });
		const elided = huge.element.querySelector("pre.arg-code").textContent;
		expect(unescapedQuotes(elided)).toBe(2);
		expect(elided).toMatch(/"\s*…\s*\(50005 characters in all\)\s*$/u);
		expect(elided.trimEnd().endsWith('"')).toBe(false);
	});

	it("cannot add a button row, or a line that reads like one", () => {
		// The other half of "the card's own closing text": the buttons. A value imitating them is
		// text in a cell, and the things that ACT are elements.
		const w = card("delete", { doctype: "ToDo", note: "T-1\n\nApprove   Deny" });

		// Exactly the three buttons the card owns: Approve, Deny, Other…
		const buttons = [...w.element.querySelectorAll("button")].map((b) => b.textContent.trim());
		expect(buttons).toEqual(["Approve", "Deny", "Other…"]);
		// And the imitation is not a line of the card at all.
		expect(lines(w)).not.toContain("Approve   Deny");
		expect(seen(w)).toContain("T-1\\n\\nApprove   Deny");
	});
});
