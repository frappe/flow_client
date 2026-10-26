import { describe, it, expect } from "vitest";
import { escapeForDisplay, quoteForDisplay, displayText, DISPLAY_LIMIT } from "@/lib/display";

// THE PANEL'S HALF OF THE SAME DEFECT.
//
// `flow/lib/agent.py` marks every code point carrying `Default_Ignorable_Code_Point`, and U+200D
// ZERO WIDTH JOINER carries it. In Sinhala, Tamil, Devanagari and every other Indic script the
// joiner is SPELLING, not decoration: a conjunct is written CONSONANT + VIRAMA + ZWJ + CONSONANT.
// This module is the port of the engine's fix, and it is a port for the reason the header of
// `lib/display.js` already gives — two escapers on one card would be two rules, and the first
// thing to drift.
//
// THE RULE, WHOLE, and identical to `_spells_rather_than_hides` in `flow/lib/agent.py`:
// a joiner (U+200C or U+200D) is kept as itself only when (1) it is at neither edge of the value,
// (2) a VIRAMA sits immediately before it, (3) a LETTER sits immediately after it, and (4) those
// two neighbours share a 128-code-point aligned block. Everything else is escaped as before.
//
// The specification both copies are measured against is `brain/40-architecture/the-invisible-character-rule.md`, and
// `flow/tests/test_s24_one_rule_four_copies.py` fails if either copy drifts from it.

const ZWJ = "\u200d";
const ZWNJ = "\u200c";
const RTL = "\u202e";

const SINHALA = "\u0dc1\u0dca\u200d\u0dbb\u0dd3 \u0dbd\u0d82\u0d9a\u0dcf"; // "Sri Lanka"
const TAMIL = "\u0b95\u0bcd\u200d\u0bb7";
const DEVANAGARI = "\u0915\u094d\u200d\u0937";

describe("a conjunct survives the card", () => {
	it("leaves a Sinhala word exactly as it was written", () => {
		expect(escapeForDisplay(SINHALA)).toBe(SINHALA);
	});

	it("leaves a Tamil conjunct exactly as it was written", () => {
		expect(escapeForDisplay(TAMIL)).toBe(TAMIL);
	});

	it("leaves a Devanagari conjunct exactly as it was written", () => {
		expect(escapeForDisplay(DEVANAGARI)).toBe(DEVANAGARI);
	});

	it("keeps a zero-width NON-joiner that asks for the separate form", () => {
		const word = "\u0dc1\u0dca\u200c\u0dbb";
		expect(escapeForDisplay(word)).toBe(word);
	});

	it("shows the word UNQUOTED, because nothing about it needed escaping", () => {
		// The quote is the panel's signal that something was escaped or elided. A word that is
		// shown as itself must not wear one, or the signal stops meaning anything.
		expect(displayText(SINHALA)).toBe(SINHALA);
	});
});

describe("a joiner with nothing to join is still marked", () => {
	it("marks one at the end of a value", () => {
		expect(escapeForDisplay("\u0dc1\u0dca\u200d")).toBe("\u0dc1\u0dca\\u200d");
	});

	it("marks one at the start of a value", () => {
		expect(escapeForDisplay("\u200d\u0dbb")).toBe("\\u200d\u0dbb");
	});

	it("marks one before a space", () => {
		expect(escapeForDisplay("\u0dc1\u0dca\u200d \u0dbb")).toBe("\u0dc1\u0dca\\u200d \u0dbb");
	});

	it("marks both halves of a doubled joiner", () => {
		expect(escapeForDisplay("\u0dc1\u0dca\u200d\u200d\u0dbb")).toBe(
			"\u0dc1\u0dca\\u200d\\u200d\u0dbb"
		);
	});

	it("marks a run of them end to end", () => {
		expect(escapeForDisplay("\u0dc1\u0dca" + ZWJ.repeat(8) + "\u0dbb")).toBe(
			"\u0dc1\u0dca" + "\\u200d".repeat(8) + "\u0dbb"
		);
	});

	it("marks one with no virama before it, however Indic the letters are", () => {
		expect(escapeForDisplay("\u0dc1\u200d\u0dbb")).toBe("\u0dc1\\u200d\u0dbb");
	});

	it("marks one between two letters of ordinary Latin", () => {
		expect(escapeForDisplay(`paid${ZWJ}unpaid`)).toBe("paid\\u200dunpaid");
	});

	// Clause 3 ON ITS OWN. Each of these sits in the SAME block as the virama, so clause 4 admits
	// it; none of them is a letter, and VIRAMA + JOINER + (vowel sign | virama | digit) spells
	// nothing. Without these four, deleting clause 3 leaves the suite green.
	it("marks one before a vowel sign of the same script", () => {
		expect(escapeForDisplay("\u0dc1\u0dca\u200d\u0dcf")).toBe("\u0dc1\u0dca\\u200d\u0dcf");
	});

	it("marks one before a second virama", () => {
		expect(escapeForDisplay("\u0dc1\u0dca\u200d\u0dca")).toBe("\u0dc1\u0dca\\u200d\u0dca");
	});

	it("marks one before a digit of the same script", () => {
		expect(escapeForDisplay("\u0dc1\u0dca\u200d\u0de6")).toBe("\u0dc1\u0dca\\u200d\u0de6");
	});

	it("marks one whose virama belongs to another script entirely", () => {
		// Clause 4, and the hole the two sibling web apps still carry: a Devanagari virama on a
		// Latin letter forms no conjunct with a Latin `x`, so the joiner between them only hides.
		expect(escapeForDisplay("SO-000A\u094d\u200dx")).toBe("SO-000A\u094d\\u200dx");
		expect(escapeForDisplay("\u0dc1\u0dca\u200d\u0937")).toBe("\u0dc1\u0dca\\u200d\u0937");
	});
});

describe("the exception reaches joiners and nothing else", () => {
	it("still marks a right-to-left override standing next to an exempt joiner", () => {
		expect(escapeForDisplay(RTL + "\u0dc1\u0dca\u200d\u0dbb")).toBe(
			"\\u202e\u0dc1\u0dca\u200d\u0dbb"
		);
	});

	it("does not let a virama license an override that follows it", () => {
		expect(escapeForDisplay("\u0dc1\u0dca\u202e\u0dbb")).toBe("\u0dc1\u0dca\\u202e\u0dbb");
	});

	it("still marks an invisible LETTER, which is what run 15 was about", () => {
		expect(escapeForDisplay("SO-0001\u3164")).toBe("SO-0001\\u3164");
	});

	it("still marks every other zero-width character", () => {
		for (const cp of [0x200b, 0x2060, 0xfeff, 0x00ad, 0x180e]) {
			const ch = String.fromCodePoint(cp);
			expect(escapeForDisplay(`a${ch}b`)).not.toBe(`a${ch}b`);
		}
	});
});

describe("two values a reader cannot tell apart still display differently", () => {
	const PAIRS = [
		["\u0dc1\u0dca\u0dbb", "\u0dc1\u0dca\u200d\u0dbb"],
		["paid", `paid${ZWJ}`],
		["SO-0001", "SO-0001\u200d"],
		["\u0dc1\u0dca\u200d\u0dbb", "\u0dc1\u0dca\u200d\u200d\u0dbb"],
		["\u0dc1\u0dca\u200d\u0dbb", "\u0dc1\u0dca\u200c\u0dbb"],
		["\u0dc1\u0dca\u200d\u0dbb", "\u0dc1\u0dca\\u200d\u0dbb"],
	];

	it.each(PAIRS)("keeps %j and %j apart", (left, right) => {
		expect(left).not.toBe(right); // positive control: they really are two values
		expect(escapeForDisplay(left)).not.toBe(escapeForDisplay(right));
	});

	it("is injective over an alphabet that contains both joiners and a virama", () => {
		const alphabet = ["\u0dc1", "\u0dca", ZWJ, ZWNJ, "\u0dbb", " "];
		const seen = new Map();
		for (const a of alphabet)
			for (const b of alphabet)
				for (const c of alphabet) {
					const value = a + b + c;
					const shown = escapeForDisplay(value);
					expect(
						seen.has(shown),
						`${JSON.stringify(value)} collides with ${JSON.stringify(seen.get(shown))}`
					).toBe(false);
					seen.set(shown, value);
				}
	});
});

describe("the panel and the engine are one rule", () => {
	// GENERATED FROM `brain/40-architecture/the-invisible-character-rule.md` §5, not typed. A
	// reviewer found that this table had been hand-copied and held 8 of the note's 21 vectors, so
	// thirteen of them were measured against the engine and never against the panel — the exact
	// drift mechanism this whole change exists to remove, reintroduced inside the drift test.
	// `flow/tests/test_s24_one_rule_four_copies.py::test_the_panel_runs_every_vector_the_note_holds`
	// now fails if this list and the note ever differ by one line.
	it.each([
		// Sinhala conjunct — kept
		["\u0dc1\u0dca\u200d\u0dbb\u0dd3", "\u0dc1\u0dca\u200d\u0dbb\u0dd3"],
		// Tamil conjunct — kept
		["\u0b95\u0bcd\u200d\u0bb7", "\u0b95\u0bcd\u200d\u0bb7"],
		// Devanagari conjunct — kept
		["\u0915\u094d\u200d\u0937", "\u0915\u094d\u200d\u0937"],
		// ZWNJ asks for the separate form — kept
		["\u0dc1\u0dca\u200c\u0dbb", "\u0dc1\u0dca\u200c\u0dbb"],
		// clause 1 — nothing after it
		["\u0dc1\u0dca\u200d", "\u0dc1\u0dca\\u200d"],
		// clause 1 — nothing before it
		["\u200d\u0dbb", "\\u200d\u0dbb"],
		// clause 3 — a space is not a letter
		["\u0dc1\u0dca\u200d \u0dbb", "\u0dc1\u0dca\\u200d \u0dbb"],
		// clause 3 — punctuation
		["\u0dc1\u0dca\u200d.\u0dbb", "\u0dc1\u0dca\\u200d.\u0dbb"],
		// clause 3 — a vowel sign of the SAME block
		["\u0dc1\u0dca\u200d\u0dcf", "\u0dc1\u0dca\\u200d\u0dcf"],
		// clause 3 — a second virama
		["\u0dc1\u0dca\u200d\u0dca", "\u0dc1\u0dca\\u200d\u0dca"],
		// clause 3 — a digit of the same script
		["\u0dc1\u0dca\u200d\u0de6", "\u0dc1\u0dca\\u200d\u0de6"],
		// doubled — both halves marked
		["\u0dc1\u0dca\u200d\u200d\u0dbb", "\u0dc1\u0dca\\u200d\\u200d\u0dbb"],
		// clause 2 — no virama, however Indic the letters
		["\u0dc1\u200d\u0dbb", "\u0dc1\\u200d\u0dbb"],
		// clause 4 — a Devanagari virama cannot license a Latin x
		["SO-000A\u094d\u200dx", "SO-000A\u094d\\u200dx"],
		// clause 4 — Sinhala virama, Devanagari letter
		["\u0dc1\u0dca\u200d\u0937", "\u0dc1\u0dca\\u200d\u0937"],
		// the original attack, untouched by the exception
		["paid\u200dunpaid", "paid\\u200dunpaid"],
		// a bidi override is not a joiner and takes no exemption
		["gnp\u202eexe", "gnp\\u202eexe"],
		// the joiner kept, the override STILL marked
		["\u202e\u0dc1\u0dca\u200d\u0dbb", "\\u202e\u0dc1\u0dca\u200d\u0dbb"],
		// a virama licenses a joiner and nothing else
		["\u0dc1\u0dca\u202e\u0dbb", "\u0dc1\u0dca\\u202e\u0dbb"],
		// the invisible LETTER run 15 closed
		["SO-0001\u3164", "SO-0001\\u3164"],
		// Malayalam U+0D3C, a virama the front ends' sixteen omit — kept
		["\u0d15\u0d3c\u200d\u0d37", "\u0d15\u0d3c\u200d\u0d37"],
		// Thai has a combining-class-9 mark and no joiner: the plain word
		["\u0e01\u0e3a\u0e02", "\u0e01\u0e3a\u0e02"],
		// clause 2 range — Thai takes no joiner, so this one only hides
		["\u0e01\u0e3a\u200d\u0e02", "\u0e01\u0e3a\\u200d\u0e02"],
		// clause 2 range — Lao U+0EBA
		["\u0eba\u200d\u0e81", "\u0eba\\u200d\u0e81"],
		// clause 2 range — Tifinagh U+2D7F is itself the consonant joiner
		["\u2d31\u2d7f\u200d\u2d30", "\u2d31\u2d7f\\u200d\u2d30"],
		// clause 2 range — Myanmar ASAT kills, it does not stack
		["\u1000\u103a\u200d\u1001", "\u1000\u103a\\u200d\u1001"],
		// clause 2 range — Brahmi NUMBER JOINER
		["\u{11005}\u{1107f}\u200d\u{11006}", "\u{11005}\u{1107f}\\u200d\u{11006}"],
		// clause 2 range — Tibetan is out of range and keeps no exception
		["\u0f40\u0f84\u200d\u0f41", "\u0f40\u0f84\\u200d\u0f41"],
		// the control — a rule that escaped everything would pass the rest
		["Sales Order SO-0001", "Sales Order SO-0001"],
	])("agrees with the note on %j", (input, expected) => {
		expect(escapeForDisplay(input)).toBe(expected);
	});
});

describe("the cap does not undo the exception", () => {
	// The reviewer's F1, on this side. `quoteForDisplay` escapes and caps in one pass and did so by
	// calling `escapeForDisplay(ch)` on ONE character at a time — and a one-character string has no
	// character either side of it, so clause 1 refused every joiner and the exception was
	// structurally unreachable on the capping path. The escaper was fixed; the card was not.
	it("quotes a Sinhala word without escaping the joiner inside it", () => {
		expect(quoteForDisplay(SINHALA)).toBe(`"${SINHALA}"`);
	});

	it("still marks a hiding joiner on the capping path", () => {
		expect(quoteForDisplay(`paid${ZWJ}unpaid`)).toBe('"paid\\u200dunpaid"');
	});

	it("states the true length when the cap cuts a conjunct short", () => {
		const shown = quoteForDisplay(SINHALA, 6);
		expect(shown.startsWith('"')).toBe(true);
		expect(shown).toContain(`(${Array.from(SINHALA).length} characters in all)`);
	});

	it("judges a joiner against the whole value, never against the prefix the cap kept", () => {
		const long = "\u0dc1\u0dca\u200d\u0dbb".repeat(40);
		expect(quoteForDisplay(long, 200)).not.toContain("\\u200d");
	});

	it("shows a long Sinhala value under the ordinary limit as itself, unquoted", () => {
		const long = "\u0dc1\u0dca\u200d\u0dbb ".repeat(20).trim();
		expect(long.length).toBeLessThan(DISPLAY_LIMIT);
		expect(displayText(long)).toBe(long);
	});

	it("keeps the conjunct when something ELSE in the value forces the quote", () => {
		// `displayText` falls through to `quoteForDisplay` as soon as anything needs escaping, and
		// that fall-through is exactly where the per-character bug lived.
		expect(displayText(`${SINHALA}\n`)).toBe(`"${SINHALA}\\n"`);
	});
});

describe("the panel's side of the one divergence between the two copies", () => {
	// Clause 3 asks Python `unicodedata.category(ch)[0] == "L"` and this copy `\p{L}`, and the two
	// runtimes ship different UCD versions — bench Python 3.14.7 is UCD 16.0.0, Node v24 is
	// Unicode 17.0. A code point one calls a letter and the other calls unassigned is a neighbour
	// the two copies decide differently. Measured 29 Sep 2026 against this commit: exactly two,
	// both added in Unicode 17, and the PANEL is the permissive side because it is the newer.
	// `flow/tests/test_s24_one_rule_four_copies.py` pins the Python half; this is the other half,
	// and between them the divergence cannot change size without a test going red.
	const VIRAMA_BLOCKS = new Set(
		[
			0x094d, 0x09cd, 0x0a4d, 0x0acd, 0x0b4d, 0x0bcd, 0x0c4d, 0x0ccd, 0x0d3b, 0x0d3c, 0x0d4d,
			0x0dca,
		].map((cp) => cp >> 7)
	);

	function lettersInViramaBlocks() {
		const out = [];
		for (let cp = 0x0900; cp < 0x0e00; cp++) {
			if (VIRAMA_BLOCKS.has(cp >> 7) && /\p{L}/u.test(String.fromCodePoint(cp)))
				out.push(cp);
		}
		return out;
	}

	it("sees exactly 572 letters where the engine sees 570", () => {
		expect(lettersInViramaBlocks().length).toBe(572);
	});

	it("names the two the engine's Unicode version does not know", () => {
		const letters = new Set(lettersInViramaBlocks());
		expect(letters.has(0x0c5c)).toBe(true); // TELUGU, added in Unicode 17
		expect(letters.has(0x0cdc)).toBe(true); // KANNADA, added in Unicode 17
	});

	it("keeps the joiner before one of them, which is the divergence itself", () => {
		// The engine escapes this joiner; this copy does not. Asserted rather than described, so
		// that if the engine's Unicode version catches up, this test is what says so.
		expect(escapeForDisplay("A్‍౜Z")).toBe("A్‍౜Z");
	});
});
