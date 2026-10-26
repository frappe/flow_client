// Model-chosen text, made safe to READ. The panel's one escaping rule, and the only one it may have.
//
// The engine already has this rule: `flow/lib/agent.py` defines `_escaped` and exports it as
// `escape_for_display`, and says in as many words that a second escaper elsewhere in the codebase
// would be a second rule and the first thing to drift. That helper is **Python-side only**. It runs
// when the engine composes the approval question, so the question's own sentence arrives at the
// panel already escaped — and the arguments beside it do not, because they are shipped as data and
// rendered by the panel itself. There is no way for the panel to call the Python helper: the values
// it renders come out of its own store, not out of a request it makes per value.
//
// So the JS side needs the same rule in one place, and this module is that place: a faithful port,
// character for character, of `_escaped` and of `_for_display` in `flow/tools/builtins.py`. It is
// deliberately a port and not an improvement. If the two ever have to differ, the difference is a
// defect in one of them.
//
// WHY, in one sentence: Vue's mustache escapes HTML and nothing else, so a newline in a value draws
// a real line inside the approval card, a right-to-left override reorders the sentence around it
// while adding no character, and a zero-width joiner is invisible by definition. Each is a way to
// show a person a question other than the one being asked, on the one surface whose whole job is to
// be trustworthy.
import { __ } from "@/lib/translate";

// The whitelist, and it has to stay one. `\p{C}` is every Other category (Cc control, Cf format,
// Cn unassigned, Co private use, Cs surrogate) and `\p{Z}` every Separator (Zs space, Zl line,
// Zp paragraph) — exactly the `C*`/`Z*` test the engine makes with `unicodedata.category(ch)[0]`.
// The engine's docstring records how it got here: the rule began as the categories that looked
// dangerous, Cc and Cf, and that list missed U+2028 and U+2029, which every layout engine treats as
// line breaks. A whitelist means a later revision of Unicode cannot quietly add a new way through.
//
// `\p{Default_Ignorable_Code_Point}` is the third term and it was MISSING, which a reviewer caught
// by measuring rather than by reading: 267 code points carry that property and are in neither C*
// nor Z*, so every one of them came through raw AND UNQUOTED — without even the quote that is
// supposed to be the signal that something was escaped. The property means precisely what this
// module is defending against: "a conformant renderer paints nothing here". Four of the 267 are
// category `Lo`, LETTERS (U+115F, U+1160, U+3164, U+FFA0), so no rule about controls, formats,
// separators or combining marks was ever going to reach them, and `SO-0001` beside
// `SO-0001<U+3164>` is two different writes that a reader cannot tell apart.
//
// It takes in the variation selectors (U+FE00-FE0F, U+E0100-E01EF) as well, and that is a decision
// rather than an oversight: an argument holding an emoji written with U+FE0F now renders quoted,
// as `"...\ufe0f"`. Slightly uglier, and correct — the cost of the other choice is a class of
// invisible character judged safe by whoever last thought about it, which is the mistake this
// whitelist exists to make impossible. The escape is visible and reversible; nothing is stripped.
const CONTROL_OR_SEPARATOR = /[\p{C}\p{Z}\p{Default_Ignorable_Code_Point}]/u;

// THE ONE DELIBERATE EXCEPTION, and it is a port of `_spells_rather_than_hides` in
// `flow/lib/agent.py`, which is itself a port of `joinsRatherThanHides` in the two sibling web
// apps. U+200D ZERO WIDTH JOINER carries `Default_Ignorable_Code_Point`, so the rule above marks
// it — correctly for every script that does not use it. In Sinhala, Tamil, Devanagari and every
// other Indic script the joiner is SPELLING: a conjunct is written CONSONANT + VIRAMA + ZWJ +
// CONSONANT, so `ශ්‍රී` is one word and marking the joiner inside it drops
// six characters of machine escape into the middle of it. The defence that exists so a person can
// read what they are approving was making the text unreadable for the people who read it.
//
// A joiner is kept ONLY when all four hold, and each clause refuses a shape an attacker uses:
//   1. it is at neither edge of the value — a joiner with nothing on one side joins nothing;
//   2. a VIRAMA sits immediately before it — that is what makes it orthography;
//   3. a LETTER sits immediately after it — which also disposes of the doubled and the run cases,
//      because the code point after the first joiner of VIRAMA ZWJ ZWJ LETTER is a joiner;
//   4. the two neighbours share a 128-code-point aligned block — without this,
//      `SO-000A` + DEVANAGARI VIRAMA + ZWJ + `x` satisfies 1 to 3 while the joiner binds nothing.
// The Indic blocks are laid out by the standard on exactly that grid. A script the clause cannot
// see keeps NO exception, which is where it was before: the rule fails closed.
const JOINERS = new Set(["\u200c", "\u200d"]);

// The viramas the exception may fire on, and the list is GENERATED, never typed:
// `flow/tests/test_s24_one_rule_four_copies.py` recomputes it from Python's `unicodedata` on every
// run and fails if one code point here differs. JavaScript's regular expressions cannot ask for a
// canonical combining class, which is the only reason the engine reads it from a library and this
// copy carries a table.
//
// TWELVE, not the sixty-nine Unicode gives for combining class 9, and the narrowing is the whole of
// an adversarial review's F2. Combining class 9 says how a mark REORDERS; it does not say that its
// script spells conjuncts with a joiner, and several that carry it do not — Thai U+0E3A PHINTHU,
// Lao U+0EBA, Tifinagh U+2D7F, Myanmar U+103A ASAT, Brahmi U+1107F NUMBER JOINER. A joiner kept
// after one of those paints nothing AND forms nothing: two different writes, one set of pixels, and
// not even a quote to say so. So the exception is confined to U+0900..U+0DFF, the ten
// Brahmi-derived blocks whose joiner orthography the standard documents — and that is also what
// makes clause 4 exact rather than a heuristic, because inside that range each 128-point block
// holds the letters of exactly one script. Measured 29 Sep 2026, UCD 16.0.0.
const VIRAMAS = new Set([
	0x094d, 0x09cd, 0x0a4d, 0x0acd, 0x0b4d, 0x0bcd, 0x0c4d, 0x0ccd, 0x0d3b, 0x0d3c, 0x0d4d, 0x0dca,
]);

const LETTER = /\p{L}/u;

/**
 * True for the joiner at `index` of `points` when it is forming a conjunct rather than hiding.
 *
 * `points` is the value as an array of CODE POINTS, so "the character before" means the character
 * before, and a surrogate pair is one neighbour rather than two. Reads `points` and nothing else.
 */
function spellsRatherThanHides(points, index) {
	if (index === 0 || index + 1 >= points.length) return false;
	const before = points[index - 1].codePointAt(0);
	const after = points[index + 1];
	if (!VIRAMAS.has(before)) return false;
	if (!LETTER.test(after)) return false;
	return before >> 7 === after.codePointAt(0) >> 7;
}

// How much escaped text the panel will show before it elides, per value.
//
// Looser than the engine's own caps (120 in `builtins.py`, 200 in `_quoted_argument`) and on purpose:
// those bound a SENTENCE a person reads in one breath, while this bounds a cell in the table a
// person consults to check the exact value that will execute. Too tight a cap here hides the data
// the table exists to show. What makes either number a cap rather than a guess is that the true
// length is always stated when anything is left out.
export const DISPLAY_LIMIT = 2000;

/**
 * Every character that could move the cursor, shown instead of obeyed.
 *
 * The backslash and the quote are escaped too. Without that, `\n` in the output could be either a
 * real line break or those two characters, and a quote inside a value could close the pair holding
 * it — the point of escaping is that the reader can tell exactly what the value was.
 */
export function escapeForDisplay(text) {
	// Split by CODE POINT, as Python does, so a surrogate pair is one character and a lone
	// surrogate is one character that `\p{Cs}` matches. An ARRAY rather than a `for…of` because the
	// joiner exception has to look at the character on either side of the one being escaped.
	const points = Array.from(String(text));
	let out = "";
	for (let index = 0; index < points.length; index++) out += escapeCodePointAt(points, index);
	return out;
}

/**
 * The displayed form of ONE code point of `points`, decided against the WHOLE value.
 *
 * THE WHOLE VALUE IS THE POINT, and this function exists because a reviewer found the place that
 * had forgotten it. `quoteForDisplay` escapes and caps in one pass, and it did so by handing
 * `escapeForDisplay` one character at a time. A one-character string has no character before or
 * after it, so clause 1 of `spellsRatherThanHides` refused every joiner unconditionally and the
 * exception was structurally unreachable there — the escaper was fixed and the card a person reads
 * was not. The same defect was in `flow/tools/builtins.py`; the engine's answer is
 * `escape_for_display_at`, and this is its port.
 *
 * `points` is the value already split into code points, so a caller in a loop splits once.
 */
export function escapeCodePointAt(points, index) {
	const ch = points[index];
	if (ch === "\\" || ch === '"') return "\\" + ch;
	if (ch === "\n") return "\\n";
	if (ch === "\r") return "\\r";
	if (ch === "\t") return "\\t";
	if (JOINERS.has(ch) && spellsRatherThanHides(points, index)) return ch;
	if (ch !== " " && CONTROL_OR_SEPARATOR.test(ch)) {
		const cp = ch.codePointAt(0);
		return cp <= 0xffff
			? "\\u" + cp.toString(16).padStart(4, "0")
			: "\\U" + cp.toString(16).padStart(8, "0");
	}
	return ch;
}

// A translated string cannot be allowed to open a line of its own: the desk reads these from
// Translation records, and one of those can carry a newline. `builtins.py` flattens for exactly this
// reason, and the string being flattened here is the one that says something was left out.
const oneLine = (text) => String(text).split(/\s+/).filter(Boolean).join(" ");

/**
 * One value, quoted, escaped, and capped — in that order, because the order is the point.
 *
 * ESCAPED FIRST, THEN CAPPED. Escaping only lengthens: one override becomes the six characters of an
 * escape sequence, so a cap of N measured on the raw value admits 6N characters of escape into the
 * card. Measuring the cap on what a person will actually read is what makes it a cap.
 *
 * The count goes OUTSIDE the closing quote (run 12's M1). Inside it, a value whose own text read
 * `short… (9999 characters in all)` was byte-identical to a genuinely elided 9 999-character value,
 * so a reader could not tell 33 characters from 9 999. `escapeForDisplay` maps `"` to `\"`, so an
 * UNESCAPED quote is a character no value can produce: it is the boundary, and everything after it
 * is the panel speaking rather than the value.
 */
export function quoteForDisplay(value, limit = DISPLAY_LIMIT) {
	const text = String(value);
	const points = Array.from(text);
	const shown = [];
	let used = 0;
	// BY INDEX INTO THE WHOLE VALUE, never a character torn out of it — see `escapeCodePointAt`.
	// The cut below decides where to STOP; it never decides what a character means.
	for (let index = 0; index < points.length; index++) {
		const escaped = escapeCodePointAt(points, index);
		if (used + escaped.length > limit) {
			const count = oneLine(__("… ({0} characters in all)", [points.length]));
			// THE CUT CAN LAND ON A JOINER THAT WAS KEPT BECAUSE OF WHAT FOLLOWED IT, and what
			// followed it is now on the other side of the cut. A joiner at the end of the shown
			// text is joining nothing — the shape clause 1 refuses — so it is escaped here, where
			// the value's true end is known. `flow/tools/builtins.py` does the same.
			const last = shown[shown.length - 1];
			if (JOINERS.has(last))
				shown[shown.length - 1] =
					"\\u" + last.codePointAt(0).toString(16).padStart(4, "0");
			return `"${shown.join("")}" ${count}`;
		}
		shown.push(escaped);
		used += escaped.length;
	}
	return `"${shown.join("")}"`;
}

/**
 * Text as a person should meet it: ITSELF when that is safe, and quoted when it is not.
 *
 * "Safe" is not "short": it means escaping would change nothing about this value AND the whole of it
 * fits. The consequence is the property the whole surface rests on — **the appearance of a quote is
 * itself the signal that something was escaped or elided.** An ordinary card looks exactly as it did
 * before this module existed; a hostile value is visibly marked as one, by a character it cannot
 * produce.
 *
 * It is NOT idempotent, and the comment that used to claim it was has been removed as false: this
 * escaper maps `\\` to `\\\\`, so text that already came out of the engine's `_escaped` is escaped a
 * second time and quoted. Never apply it to engine-escaped text — the question's own sentence arrives
 * at the panel already escaped, and it is rendered as it arrived, by nobody's second rule.
 */
export function displayText(value, limit = DISPLAY_LIMIT) {
	const text = String(value);
	if (text.length <= limit && escapeForDisplay(text) === text) return text;
	return quoteForDisplay(text, limit);
}

/**
 * One scalar argument value, ready to read.
 *
 * The type handling is `formatScalar`'s, unchanged, and the reason it survives is the reason
 * `_display_json` gives for the same decision in the engine: a type that cannot carry an escape is
 * shown as ITSELF, not as text. Quoting everything made a cleared field indistinguishable from a
 * model writing the four letters "None", and a quantity of 3 indistinguishable from the character
 * "3" — different writes, and the approval surface has to tell them apart. Only a string can hide a
 * control character inside it, and only a string is quoted.
 *
 * A number is shown as itself only when that is safe. In JavaScript that is a weaker condition than
 * in Python — `JSON.parse` cannot produce a 3 000-digit integer or a bigint, so the only unsafe
 * numbers are `NaN` and `±Infinity`, which are not JSON but which model output supplies anyway.
 */
export function displayScalar(value, limit = DISPLAY_LIMIT) {
	if (value === null || value === undefined || value === "") return "—";
	if (typeof value === "boolean") return value ? __("Yes") : __("No");
	if (typeof value === "object") return "—"; // empty {} / [] — non-empty renders elsewhere
	if (typeof value === "number")
		return Number.isFinite(value) ? String(value) : quoteForDisplay(String(value), limit);
	return displayText(String(value), limit);
}
