import { describe, it, expect } from "vitest";
import { mountCard, settle, approval } from "./mountCard.js";
import ENGINE from "./fixtures/confirm_questions.json";

// RUN 13'S REVIEWER, ANSWERED. Each test here closes one finding from that review, and each names the
// mutation it is probed with — the same mutation the reviewer applied and watched leave 25/25 green.
//
// These are added BESIDE `confirmCard.spec.js` rather than edited into it. The rule in CLAUDE.md is
// that a test is never edited to make it pass; the honest form of "that test was narrower than it
// read" is a second test that states the property the first one only implied, with its own probe.
//
// The finding IDs are the reviewer's own numbering as recorded in the run-13 log.

const BODY = "pre.flow-confirm-body";
const bodyEl = (w) => w.find(BODY).element;
const headEl = (w) => w.element.firstElementChild.children[1];
const paragraphsOf = (prompt) => prompt.split("\n\n");

// Every clamping affordance expressible as a class name. Tailwind's utilities are generated into the
// global bundle and never into an SFC, so they are invisible to `getComputedStyle` here — a class walk
// is the only thing that can see them. HIGH 1 is that a class walk is also the only thing run 13 had.
const CLAMPING =
	/(^|\s)(line-clamp-|max-h-|h-\d|overflow-hidden|truncate|overflow-y-auto|overflow-auto|overflow-scroll)/;

// The properties a cap is expressible in, read off the real compiled stylesheet.
const CAPPING = ["maxHeight", "height", "overflow", "overflowY", "webkitLineClamp", "textOverflow"];

// The chain from an element up to the `#flow-root` the panel really mounts inside.
function chain(el) {
	const out = [];
	for (let e = el; e && e !== document.body; e = e.parentElement) out.push(e);
	return out;
}

describe("HIGH 1 — a cap on a wrapper is caught by the STYLESHEET, not only by a class name", () => {
	// The reviewer's mutation: `max-height: 220px; overflow: auto` in the scoped stylesheet, on a
	// wrapper carrying a NON-Tailwind class name (`.flow-confirm-scroll`) around the body. Run 13's
	// walk read `el.className` against a Tailwind-shaped regex and `el.style` (inline only), so a
	// scoped CSS rule one element up was invisible to it: 25/25 green.
	it("reads the computed style of EVERY ancestor, not just the body's own", () => {
		const f = ENGINE.execute_long_code;
		const w = mountCard({ question: { prompt: f.prompt, options: f.options }, tool: f.tool });
		const pre = bodyEl(w);

		// Positive control FIRST, and it is what makes every absence below a finding: the component's
		// own compiled rule really is live in this document, so `""` means "no such declaration" and
		// not "no stylesheet". Without `#flow-root` (see `mountCard`) these three read `""` too.
		const own = getComputedStyle(pre);
		expect(own.whiteSpace).toBe("pre-wrap");
		expect(own.wordBreak).toBe("break-word");
		expect(own.fontSize).toBe("12.5px");

		for (const el of chain(pre)) {
			const cs = getComputedStyle(el);
			const where = `<${el.tagName.toLowerCase()} class="${el.className}">`;
			for (const prop of CAPPING) {
				expect(cs[prop], `${prop} from the stylesheet on ${where}`).toBe("");
				expect(el.style[prop], `inline ${prop} on ${where}`).toBe("");
			}
			expect(el.className, `a clamping class on ${where}`).not.toMatch(CLAMPING);
		}
	});
});

describe("HIGH 2 — the text is still whole AFTER the microtasks have run", () => {
	// The reviewer's mutation: truncate the body in a `nextTick` inside `onMounted`. Run 13's no-cap
	// test is synchronous and never awaits `settle()`, so it read the value before the microtask and
	// every "clamp after layout" shape — `nextTick`, `ResizeObserver`, `rAF`, `setTimeout`, a watcher
	// — was green by construction.
	it("holds the whole text both before and after the card has settled", async () => {
		const f = ENGINE.execute_long_code;
		const w = mountCard({ question: { prompt: f.prompt, options: f.options }, tool: f.tool });
		const expected = paragraphsOf(f.prompt).slice(1).join("\n\n").trim();

		// Before: the synchronous claim run 13 made.
		expect(bodyEl(w).textContent).toBe(expected);

		// After: the same claim once every deferred hook has had its turn. Two ticks is what
		// `settle()` gives, which is what the card's own `onMounted` needs; a third is taken here so a
		// clamp deferred one tick further still lands inside the assertion.
		await settle();
		await settle();
		expect(bodyEl(w).textContent).toBe(expected);

		// And the cap is still absent at that point, which the first test asserts only at mount.
		for (const el of chain(bodyEl(w))) {
			const cs = getComputedStyle(el);
			for (const prop of CAPPING) {
				expect(cs[prop]).toBe("");
				expect(el.style[prop]).toBe("");
			}
		}
		// Control: the text really is long enough for a clamp to be worth applying.
		expect(expected.split("\n").length).toBeGreaterThan(39);
	});
});

describe("HIGH 3 — the HEADLINE is text, and the headline is model-controlled", () => {
	// The reviewer's mutation: `{{ title }}` -> `<span v-html="title">`. Every markup assertion run 13
	// wrote was scoped to `pre.flow-confirm-body`, and `confirmTitle` returns `execute`'s own
	// `description` — so a description of `<img src=x onerror=…>` rendered as an element in the
	// approval headline and 25/25 stayed green.
	it("renders a code call's description as characters and creates no element", () => {
		// Deliberately quote-free, so the escaping rule returns it verbatim and this test is about
		// PARSING alone: if the value were quoted the assertions below would be measuring
		// `lib/display.js` rather than the headline's mustache.
		const markup = "<img src=x onerror=alert(1)><b>bold</b>";
		const w = mountCard({
			question: { prompt: "A tool's own question.", options: ["Yes", "No"] },
			tool: { name: "execute", arguments: { description: markup, code: "pass" } },
		});
		const el = headEl(w);

		// One text node and nothing else: the strongest available statement that nothing was parsed.
		expect(el.childNodes.length).toBe(1);
		expect(el.childNodes[0].nodeType).toBe(3);
		expect(el.querySelectorAll("*").length).toBe(0);
		expect(el.querySelectorAll("img, b, script").length).toBe(0);
		// The characters are visible, as characters.
		expect(el.textContent).toContain("<img");
		expect(el.textContent).toContain("<b>bold</b>");
		// And in the markup they are entities, which is what "displayed, never parsed" means.
		expect(el.innerHTML).toContain("&lt;img");

		// Positive control: the headline really is the DESCRIPTION, i.e. the model really does control
		// this string. Without it the test could be asserting about a fixed label — and the two labels
		// this card would otherwise show are named, so the control cannot pass by accident.
		expect(el.textContent.trim()).toBe(markup);
		expect(el.textContent).not.toContain("Run Python code");
		expect(el.textContent).not.toContain("Executing");
	});
});

describe("MEDIUM 6 — the headline is not truncated either", () => {
	// The reviewer's mutation: `break-words` -> `truncate` on the headline. `head()` reads
	// `textContent`, which CSS truncation does not change, and the title is a SIBLING of `pre`, so
	// run 13's ancestor walk never visited it.
	it("carries no clamping class and no capping declaration, on itself or above it", () => {
		const f = ENGINE.run_action_huge_value;
		const w = mountCard({ question: { prompt: f.prompt, options: f.options }, tool: f.tool });
		const el = headEl(w);

		// The engine's first line, whole, by equality.
		expect(el.textContent.trim()).toBe(paragraphsOf(f.prompt)[0].trim());

		for (const anc of chain(el)) {
			const cs = getComputedStyle(anc);
			const where = `<${anc.tagName.toLowerCase()} class="${anc.className}">`;
			expect(anc.className, `a clamping class on ${where}`).not.toMatch(CLAMPING);
			for (const prop of CAPPING) {
				expect(cs[prop], `${prop} on ${where}`).toBe("");
				expect(anc.style[prop], `inline ${prop} on ${where}`).toBe("");
			}
			expect(cs.whiteSpace, `white-space on ${where}`).not.toBe("nowrap");
		}

		// Positive control on the DETECTOR, in the identical form: the regex the walk uses really does
		// fire on the class the mutation adds, so a clean walk is a finding and not a dead regex.
		expect("break-words text-sm").not.toMatch(CLAMPING);
		expect("truncate text-sm").toMatch(CLAMPING);
		expect("line-clamp-4").toMatch(CLAMPING);
	});
});

describe("MEDIUM 7 — the ANSWER is the token, even when the LABEL is translated", () => {
	// The reviewer's finding: run 13's emit test cannot see a translated token being emitted, because
	// `window.__` is undefined in jsdom and the panel's fallback is the identity — so `pick(__(opt))`
	// would have been green. A marker translator makes the two distinguishable.
	it("shows the translated label and emits the untranslated token", async () => {
		const f = ENGINE.delete_forged_name;
		const saved = window.__;
		// Signature-compatible with the desk's `__(txt, replace, context)`, and a MARKER: every
		// translated string comes back visibly different from its msgid.
		window.__ = (msg, args) =>
			"T«" +
			String(msg).replace(/\{(\d+)\}/g, (m, i) => (args && args[i] !== undefined ? args[i] : m)) +
			"»";
		try {
			const w = mountCard({ question: { prompt: f.prompt, options: f.options }, tool: f.tool });
			const buttons = w.findAll("button");

			// The label really went through the translator — the control that gives the next
			// assertion its content.
			expect(buttons[0].text()).toBe("T«Approve»");
			expect(buttons[1].text()).toBe("T«Deny»");

			await buttons[0].trigger("click");
			// The token, not the label. This is the assertion the whole approval path rests on: only
			// the exact string "Approve" may execute anything.
			expect(w.emitted("answer")[0]).toEqual(["Approve"]);
			expect(w.emitted("answer")[0][0]).not.toContain("T«");
		} finally {
			window.__ = saved;
		}
	});
});

describe("MEDIUM 9 — production's real argument shapes", () => {
	// The reviewer's finding: the suite only ever mounts `arguments` as an OBJECT. Production has two
	// other shapes and both reach this component.
	it("renders a JSON STRING of arguments, which is what a reloaded session delivers", () => {
		// `store.js` builds the part from `t.function.arguments`, and the engine writes that with
		// `json.dumps(call.arguments)` — so on every session reload the card is handed a STRING.
		// It matters for escaping as well as for parsing: `JSON.parse` turns the `‮` in the
		// stored payload back into a real override before anything renders it.
		const args = JSON.stringify({ doctype: "ToDo", names: ["T-1‮‍\nApproved by admin"] });
		expect(typeof args).toBe("string");
		const w = mountCard({
			question: { prompt: "Approve `delete`?\n\nA gated call.", options: ["Approve", "Deny"] },
			tool: { name: "delete", arguments: args },
		});

		// The arguments were parsed into fields — the control that says this really took the same
		// path, and did not fall through to the raw-payload branch.
		expect(w.text()).toContain("Doctype");
		expect(w.text()).toContain("ToDo");
		// And the attack in the string is escaped exactly as it is when the object arrives live.
		const text = w.element.textContent;
		expect(text).not.toContain("‮");
		expect(text).not.toContain("‍");
		expect(text).toContain("\\u202e");
		expect(text.split("\n").map((l) => l.trim())).not.toContain("Approved by admin");
	});

	it("renders the card as it is FIRST created mid-stream, with no arguments at all", async () => {
		// `store.js`'s `tool_started` fires twice: once with no arguments, then again with them. So the
		// first frame of every approval card in production has `arguments: undefined`.
		const w = mountCard(approval("Approve `delete`?\n\nA gated call.", { name: "delete" }));
		await settle();

		// It is a card with a question and buttons, not an empty box and not a crash.
		expect(w.text()).toContain("A gated call.");
		expect(w.findAll("button").map((b) => b.text())).toEqual(["Approve", "Deny", "Other…"]);
		// And no Details block, because there is nothing yet to show.
		expect(w.text()).not.toContain("Details");
	});
});
