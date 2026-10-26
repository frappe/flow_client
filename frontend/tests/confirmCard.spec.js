import { describe, it, expect } from "vitest";
import { mountCard, settle, approval, engineQuestion } from "./mountCard.js";
import { reactive } from "vue";
import { scrollCalls } from "./setup.js";
import ENGINE from "./fixtures/confirm_questions.json";

// What a person actually sees on the Desk approval card, asserted on the RENDERED DOM.
//
// This file replaces the claims of `flow/tests/test_s21_confirm_card_source.py`, which says in its
// own docstring that it "proves no pixel, no layout and no behaviour" and reads the component off
// disk as text. Run 12's QA adversary broke that guard twice in one move each and wrote: *a source
// guard can only assert on strings that happen to be in the file, and every way of hiding the
// approval text … is a string it was not told about … each new assertNotIn buys one mutation and not
// the property.* The answer is to stop asserting about the file and start asserting about the screen.
//
// Two rules hold throughout, and both exist because breaking them is how a render test becomes a
// source guard wearing a costume:
//
// 1. NOTHING here reads the component's source. Every expectation is `textContent`, `innerHTML`, a
//    computed style, an element count, `document.activeElement`, or an observed call.
// 2. The questions come from `./fixtures/confirm_questions.json`, which is the output of the real
//    `_confirmation_question`, kept honest by `flow/tests/test_s21_card_fixture_is_current.py` — it
//    rebuilds every one from the live engine on each bench run and goes RED on any drift. So these
//    tests are driven by what the engine produces, not by a string that resembles it.

const BODY = "pre.flow-confirm-body";
const RTL = "‮"; // RIGHT-TO-LEFT OVERRIDE
const ZWJ = "‍"; // ZERO WIDTH JOINER

// The card's own two halves, as the reader meets them: the headline, then the block beneath it.
// The headline is located structurally — the card root's first child is the icon+title row, whose
// second child is the title — rather than by a utility class, which several cells in the arguments
// table also carry.
const head = (w) => w.element.firstElementChild.children[1].textContent.trim();
const bodyEl = (w) => w.find(BODY).element;
// feather renders its name into the svg's own class (`feather feather-alert-triangle`), so the icon
// a person sees is readable off the rendered tree.
const iconClass = (w) => w.element.querySelector("svg").getAttribute("class");

// `prompt.split("\n\n")` is how the engine joined it and how the card splits it back.
const paragraphsOf = (prompt) => prompt.split("\n\n");

describe("the engine's question reaches the reader whole", () => {
	it("shows every paragraph, including the first, and drops nothing between them", () => {
		const f = ENGINE.delete_forged_name;
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		const paras = paragraphsOf(f.prompt);

		// Paragraph 0 is the engine's own head line and is the headline; the rest is the block.
		expect(head(w)).toBe(paras[0].trim());
		expect(bodyEl(w).textContent).toBe(paras.slice(1).join("\n\n").trim());

		// The property the two assertions above exist for, stated on its own so it cannot be
		// satisfied by a lucky split: every paragraph of the question is somewhere on the card.
		for (const p of paras) expect(w.text()).toContain(p.trim());
	});

	it("does not drop the first paragraph when the headline is NOT the engine's own line", () => {
		// A tool may return a Question of its own, whose paragraph 0 is the tool's words rather than
		// the engine's. Then the headline is the client's label, and paragraph 0 would be shown
		// nowhere at all unless the body becomes the WHOLE prompt. (The security review's L3.)
		const prompt = "A sentence a tool wrote\n\nand its second paragraph";
		const w = mountCard({
			question: { prompt, options: ["Yes", "No"] }, // NOT Approve/Deny: not an approval question
			tool: { name: "delete", arguments: { doctype: "ToDo", names: ["T-1"] } },
		});
		expect(bodyEl(w).textContent).toBe(prompt);
		expect(w.text()).toContain("A sentence a tool wrote");
	});
});

describe("markup in a question is displayed, never parsed", () => {
	// Asserted on innerHTML, not textContent: `textContent` reads the same whether the browser
	// parsed `<b>` into an element or printed it, so a textContent-only assertion cannot tell a
	// displayed tag from an executed one.
	it("renders a script tag, an HTML tag and a markdown image as visible characters and creates no element", () => {
		const hostile =
			"<script>alert(1)</script><b>bold</b><img src=x onerror=alert(2)>![i](http://h/i.png)";
		const w = mountCard(
			approval(`Approve \`delete\`?\n\n${hostile}`, {
				name: "delete",
				arguments: { doctype: "ToDo", names: ["T-1"] },
			})
		);
		const pre = bodyEl(w);

		// Visible characters: the angle brackets arrive as entities, so they were printed.
		expect(pre.innerHTML).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
		expect(pre.innerHTML).toContain("&lt;b&gt;bold&lt;/b&gt;");
		expect(pre.innerHTML).toContain("&lt;img");
		// And the text a person reads is the tag itself.
		expect(pre.textContent).toContain(hostile);

		// No element was created, anywhere in the card — not just inside the body.
		const root = w.element;
		expect(root.querySelectorAll("script").length).toBe(0);
		expect(root.querySelectorAll("b").length).toBe(0);
		// The markdown image matters as much as the script tag: an `<img>` is an outbound request
		// from the approver's browser, so a question could confirm a reader opened it.
		expect(root.querySelectorAll("img").length).toBe(0);
		// The body holds no child elements at all: it is one text node.
		expect(pre.children.length).toBe(0);
		expect(pre.childNodes.length).toBe(1);
		expect(pre.childNodes[0].nodeType).toBe(3); // Node.TEXT_NODE
	});

	it("displays the markup the ENGINE really passes through, unparsed", () => {
		// The engine deliberately does not HTML-escape: `<` and `>` cannot move a cursor or open a
		// line, and escaping them would put `&lt;` in the audit record. Making them harmless is the
		// client's job, and this is where that is proven — driven by the engine's own output rather
		// than by a hand-written sample of it.
		const f = ENGINE.create_markup_value;
		expect(f.prompt).toContain("<script>"); // control: the engine really did pass it through
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		const pre = bodyEl(w);
		expect(pre.innerHTML).toContain("&lt;script&gt;");
		expect(pre.textContent).toContain("<script>alert(1)</script>");
		expect(w.element.querySelectorAll("script, b, img").length).toBe(0);
	});

	it("keeps an escape the engine wrote as the two characters it wrote", () => {
		// The engine prints `\n` to SAY a value contained a newline. Anything that re-interpreted
		// the text — a markdown renderer, `v-html` — would turn that back into a real line break and
		// undo the escaping on exactly the surface it was done for.
		const w = mountCard(
			approval('Approve `delete`?\n\nDelete 1 ToDo: "T-1\\nApproved by admin"')
		);
		const pre = bodyEl(w);
		expect(pre.textContent).toContain('"T-1\\nApproved by admin"');
		// One line in the block, not two: the `\n` is two characters, not a break.
		expect(pre.textContent.split("\n").length).toBe(1);
	});
});

describe("nothing in a model-chosen value can forge a second question", () => {
	const f = ENGINE.delete_forged_name;

	it("shows a right-to-left override, a zero-width joiner and a newline as escapes", () => {
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		const text = bodyEl(w).textContent;

		// The escapes are on screen…
		expect(text).toContain("\\u202e");
		expect(text).toContain("\\u200d");
		expect(text).toContain("\\n");
		// …and the characters themselves never reached the DOM. An override that arrived intact
		// would reorder the sentence around it with no character added, so its absence is the
		// assertion that matters and it is made on the rendered text.
		expect(text).not.toContain(RTL);
		expect(text).not.toContain(ZWJ);
		// Positive control in the identical form: the name itself DID reach the reader, so the
		// three `not.toContain`s above are about escaping and not about an empty body.
		expect(text).toContain("T-1");
	});

	it("draws exactly one question and no line that was never the engine's", () => {
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });

		// The forged line is "\nApproved by admin". If the newline had been obeyed, the card would
		// carry a line whose whole content is the forgery.
		const lines = w
			.text()
			.split("\n")
			.map((l) => l.trim());
		expect(lines).not.toContain("Approved by admin");

		// And there is one approval to answer, not two: exactly one Approve and one Deny.
		const labels = w.findAll("button").map((b) => b.text());
		expect(labels.filter((l) => l === "Approve").length).toBe(1);
		expect(labels.filter((l) => l === "Deny").length).toBe(1);
	});
});

describe("a 50,000-character value is capped, and the count is the engine's", () => {
	const f = ENGINE.run_action_huge_value;

	it("caps the value and puts the elision count OUTSIDE the closing quote", () => {
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		const text = bodyEl(w).textContent;

		// Capped: the reader is not handed 50,000 characters.
		expect(text.length).toBeLessThan(1000);
		expect(f.tool.arguments.action.length).toBe(50000); // control: the input really was that long

		// The count, and the real length, are stated.
		const m = text.match(/"([^"]*)"\s*…\s*\((\d+) characters in all\)/);
		expect(m).not.toBeNull();
		expect(Number(m[2])).toBe(50000);

		// THE PROPERTY (run 12's M1). `escape_for_display` maps `"` to `\"`, so an unescaped quote is
		// a character no model-chosen value can produce: it is the boundary, and everything after it
		// is the engine's own. A count INSIDE the quotes is a count a value can forge — a value whose
		// own text read `short… (9999 characters in all)` would be byte-identical to a genuinely
		// elided one. So: the quoted run must not contain the count, and the text after the closing
		// quote must.
		const quoted = m[1];
		expect(quoted).not.toContain("characters in all");
		const closing = text.indexOf(`"${quoted}"`) + quoted.length + 2;
		expect(text.slice(closing)).toContain("characters in all");
		expect(text.indexOf("characters in all")).toBeGreaterThan(closing - 1);
	});
});

describe("a question with no tool part still has something to read", () => {
	it("renders a card carrying the question when there is no tool at all", () => {
		const w = mountCard({
			question: { prompt: "Shall I go ahead?", options: ["Approve", "Deny"] },
			tool: null,
		});
		// The one-paragraph case: there is no body to put under a headline, so the headline is it.
		// The assertion is that the question is ON the card, wherever the card chose to put it —
		// which is the user-visible claim, and is not satisfied by a card of two buttons.
		expect(w.text()).toContain("Shall I go ahead?");
		expect(w.findAll("button").length).toBeGreaterThan(0);
	});

	it("renders both paragraphs when there is no tool and the question has a body", () => {
		const w = mountCard({
			question: {
				prompt: "Shall I go ahead?\n\nIt will change three records.",
				options: ["Approve", "Deny"],
			},
			tool: null,
		});
		expect(head(w)).toBe("Shall I go ahead?");
		expect(bodyEl(w).textContent).toBe("It will change three records.");
	});

	it("renders a gated call that has no arguments at all", () => {
		// A6: the empty-card case the sibling web apps shipped — a gated call with no arguments drew
		// a label and two buttons and nothing else.
		const w = mountCard(
			approval("Approve `reindex`?\n\nRebuild the search index.", {
				name: "reindex",
				arguments: {},
			})
		);
		expect(bodyEl(w).textContent).toBe("Rebuild the search index.");
		// And no Details table, because there is nothing to put in it.
		expect(w.text()).not.toContain("Details");
	});
});

describe("a long question scrolls rather than truncates", () => {
	const f = ENGINE.execute_long_code;

	it("holds the WHOLE text, with no cap and no internal scroll, and no clamp anywhere above it", () => {
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		const pre = bodyEl(w);
		const expected = paragraphsOf(f.prompt).slice(1).join("\n\n").trim();

		// The full text, by EQUALITY and not by `toContain`: a `slice(0, 200)` in the computed would
		// satisfy any substring assertion written against the beginning of the value.
		expect(pre.textContent).toBe(expected);
		expect(expected.split("\n").length).toBeGreaterThan(39); // control: it really is 40 lines
		expect(pre.textContent).toContain("row_39 ="); // and the LAST line is present

		// The computed style, from the component's real compiled stylesheet. `mountCard` puts the
		// card inside `#flow-root` because every rule ships prefixed with it; without that container
		// every property below reads "" and this test would pass against a 220px cap.
		const cs = getComputedStyle(pre);
		// Positive controls first, in the identical form, from the SAME rule: if these are empty the
		// stylesheet did not match and the two assertions after them mean nothing.
		expect(cs.whiteSpace).toBe("pre-wrap");
		expect(cs.wordBreak).toBe("break-word");
		expect(cs.fontSize).toBe("12.5px");
		// Now the absences, which are the point: the block has no height cap and no scroller of its
		// own, so it grows and the message list around it scrolls.
		expect(cs.maxHeight).toBe("");
		expect(cs.overflow).toBe("");
		expect(cs.overflowY).toBe("");
		expect(cs.height).toBe("");

		// THE MUTATION THE STYLESHEET CANNOT SEE. Run 12's QA broke the source guard with a Tailwind
		// `line-clamp-4` on a WRAPPER: Tailwind's utilities are generated into the global bundle, not
		// into this SFC, so they are invisible both to a stylesheet assertion and to
		// `getComputedStyle` here. The rendered ancestor chain is not invisible. Walk it.
		const CLAMPING =
			/(^|\s)(line-clamp-|max-h-|h-\d|overflow-hidden|truncate|overflow-y-auto|overflow-auto|overflow-scroll)/;
		for (let el = pre; el && el !== document.body; el = el.parentElement) {
			expect(el.className, `a clamping class on <${el.tagName.toLowerCase()}>`).not.toMatch(
				CLAMPING
			);
			// An inline style carries a cap no stylesheet and no class list would show.
			expect(el.style.maxHeight, `inline max-height on <${el.tagName.toLowerCase()}>`).toBe(
				""
			);
			expect(el.style.overflow, `inline overflow on <${el.tagName.toLowerCase()}>`).toBe("");
			expect(el.style.overflowY).toBe("");
			expect(el.style.height).toBe("");
			expect(el.style.webkitLineClamp).toBe("");
		}
	});

	it("offers no affordance that hides part of the text", () => {
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		// The same defect wearing a button. Asserted on the rendered labels, so a "Show more" built
		// by any component at all is caught, not only the two the source guard knew by name.
		for (const label of w.findAll("button").map((b) => b.text()))
			expect(label).not.toMatch(/show more|show less|expand|more…|\.\.\.more/i);
		expect(w.text()).not.toMatch(/show more/i);
	});
});

describe("nothing answers for the person before they have read the question", () => {
	it("gives focus to neither Approve nor Deny on mount", async () => {
		const f = ENGINE.delete_forged_name;
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		await settle();

		// Observed on the document, not inferred from the absence of an `autofocus` string.
		expect(document.activeElement).toBe(document.body);
		expect(w.element.contains(document.activeElement)).toBe(false);
		for (const b of w.findAll("button")) {
			expect(b.element).not.toBe(document.activeElement);
			expect(b.element.hasAttribute("autofocus")).toBe(false);
		}
	});

	it("puts the card's own top on screen when it mounts, not the button row", async () => {
		// D6 / A10, half of it. Run 12 could only grep the source for `scrollIntoView({ block:
		// "start"`. Here the call is observed, with its target and its arguments.
		const f = ENGINE.execute_long_code;
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		await settle();

		expect(scrollCalls.length).toBe(1);
		expect(scrollCalls[0].options.block).toBe("start");
		// The element scrolled to is the CARD ROOT — so the question is what comes on screen.
		expect(scrollCalls[0].el).toBe(w.element);
	});

	it("does not yank the view to a question that was already answered", async () => {
		const f = ENGINE.delete_forged_name;
		mountCard({
			question: { prompt: f.prompt, options: f.options, _answer: "Approve" },
			tool: f.tool,
		});
		await settle();
		expect(scrollCalls.length).toBe(0);
	});
});

describe("no code path puts raw tool arguments where the question belongs", () => {
	it("fills the body with the engine's escaped sentence, never with a dump of the arguments", () => {
		// Run 12 measured this mutation (its T4-P1): blank the engine's `confirm_prompt` branch and
		// the question falls through to a JSON dump of the same arguments — which contains the same
		// values, so an assertion written on the values cannot tell the two apart. What tells them
		// apart is that a dump carries the ARGUMENT SHAPE and the raw, unescaped characters.
		const f = ENGINE.delete_forged_name;
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		const text = bodyEl(w).textContent;

		// The argument shape is absent from the body.
		for (const key of ['"names"', '"doctype"', '"action"', '"records"'])
			expect(text).not.toContain(key);
		// The raw characters are absent from the body — the distinctive values arrive escaped only.
		expect(text).not.toContain(RTL);
		expect(text).not.toContain(ZWJ);
		// Positive control: the body is not empty and does name what will happen.
		expect(text.length).toBeGreaterThan(10);
		expect(text).toContain("ToDo");
	});

	it("shows a code call's own sentence above its code, and the code whole", () => {
		const f = ENGINE.execute_long_code;
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		const text = bodyEl(w).textContent;
		expect(text).toContain("Count the open records");
		// The code is last and complete — shortening it is the E5 v1 truncation attack.
		expect(text).toContain("row_0 =");
		expect(text).toContain("row_39 =");
		// And the body is the tool's sentence, not the argument dump (run 12's own strengthened
		// assertion, now made about the screen rather than about the payload).
		expect(text).not.toContain('"code"');
	});
});

describe("what was true before S21 is still true", () => {
	it("still renders the arguments, BELOW the body", () => {
		// A5. Asserted by document order in the rendered tree, which is what a reader experiences —
		// not by the index of two strings in a source file.
		const f = ENGINE.delete_forged_name;
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		const pre = bodyEl(w);
		expect(w.text()).toContain("Details");
		const details = [...w.element.querySelectorAll("*")].find(
			(e) => e.textContent.trim() === "Details"
		);
		expect(details).toBeTruthy();
		// DOCUMENT_POSITION_FOLLOWING === 4: the details block comes after the body.
		expect(pre.compareDocumentPosition(details) & 4).toBe(4);
	});

	it("still marks a delete as dangerous and a read as not", () => {
		// A8, by the rendered icon rather than by the `danger` computed.
		const f = ENGINE.delete_forged_name;
		const del = mountCard({
			question: engineQuestion(f),
			tool: f.tool,
		});
		expect(iconClass(del)).toContain("feather-alert-triangle");

		const safe = mountCard(
			approval("Approve `read`?\n\nRead 10 ToDo records.", {
				name: "read",
				arguments: { doctype: "ToDo" },
			})
		);
		expect(iconClass(safe)).toContain("feather-shield");
		expect(iconClass(safe)).not.toContain("feather-alert-triangle");
	});

	it("still emits exactly the option token that was clicked", async () => {
		// A9. The tokens are stable; `optLabel` translates for DISPLAY only and `pick()` emits the
		// token itself. A translation that changed what is emitted would change what executes.
		const f = ENGINE.delete_forged_name;
		const w = mountCard({ question: engineQuestion(f), tool: f.tool });
		const buttons = w.findAll("button");

		await buttons.find((b) => b.text() === "Approve").trigger("click");
		expect(w.emitted("answer")).toEqual([["Approve"]]);

		const w2 = mountCard({ question: engineQuestion(f), tool: f.tool });
		await w2
			.findAll("button")
			.find((b) => b.text() === "Deny")
			.trigger("click");
		expect(w2.emitted("answer")).toEqual([["Deny"]]);
	});
});

describe("the headline names the action, and the engine's own line is never lost", () => {
	it("is the engine's first line for an approval question, and the client's label otherwise", () => {
		// A7, the last of the spec's BROWSER rows that had no render proof. Both halves are asserted
		// in one test on purpose: either half alone is unfalsifiable, because a card that ALWAYS
		// showed the engine's line, and a card that ALWAYS showed the client's label, each satisfy
		// one of them. The rule only has content where the two differ, so that is asserted too.
		const f = ENGINE.delete_forged_name;
		const engineFirstLine = paragraphsOf(f.prompt)[0].trim();

		// (i) the engine's own approval pair, with a body under the head line: the headline is the
		// engine's sentence, so the approver reads what the engine asked and not a label for it.
		const asked = mountCard({
			question: engineQuestion(f),
			tool: f.tool,
		});
		expect(head(asked)).toBe(engineFirstLine);

		// (ii) the SAME tool and the SAME prompt, but a question that is not the engine's pair — a
		// tool returning a Question of its own. Now the headline is the client's label, computed from
		// the arguments, and paragraph 0 moves into the body (proved by the test above) rather than
		// being dropped.
		// The label is a TRANSLATED string with a positional placeholder, and the desk's global
		// translator is what fills it in. `lib/translate.js` falls back to returning the message
		// unsubstituted when that global is absent, so a bare jsdom would render the literal
		// "Delete 1 {0} record" and this test would be asserting the fallback instead of the card.
		// The global is therefore stubbed with the desk's own substitution for the length of the
		// assertion, and restored after it. (Measured 27 Sep 2026: without this the head is
		// "Delete 1 {0} record" — see the FINDING in the run log.)
		const savedTranslator = window.__;
		window.__ = (msg, args) =>
			String(msg).replace(/\{(\d+)\}/g, (m, i) =>
				args && args[i] !== undefined ? args[i] : m
			);
		let returnedHead;
		try {
			const returned = mountCard({
				question: { prompt: f.prompt, options: ["Yes", "No"] },
				tool: f.tool,
			});
			returnedHead = head(returned);
		} finally {
			window.__ = savedTranslator;
		}
		expect(returnedHead).toBe("Delete 1 ToDo record");

		expect(returnedHead).not.toBe(head(asked));
	});
});

describe("the free-text answer is the person's own words, and only theirs", () => {
	// The question object is `reactive()` here for the same reason it is reactive in production: the
	// card writes `_showOther` and `_otherText` back onto the question it was handed, and the store's
	// object is reactive. A plain object would never re-render, and every assertion below would be
	// made against the button row instead of the textarea — green, and about nothing.
	const openOther = async (w) => {
		await w
			.findAll("button")
			.find((b) => b.text() === "Other…")
			.trigger("click");
		await settle();
	};
	const button = (w, label) => w.findAll("button").find((b) => b.text() === label);

	it("emits exactly what was typed, and emits nothing at all for whitespace", async () => {
		// A9's third token. Approve and Deny are fixed strings the card owns; "Other" is the one
		// answer whose content comes from the person, so the thing to prove is that it arrives
		// unchanged and that an empty one never becomes an answer.
		const f = ENGINE.delete_forged_name;
		const w = mountCard({
			question: reactive(engineQuestion(f)),
			tool: f.tool,
		});
		await openOther(w);

		const ta = w.find("textarea");
		expect(ta.exists()).toBe(true);
		// Approve and Deny are no longer reachable while the box is open: there is no second way to
		// answer that a stray click could take.
		expect(button(w, "Approve")).toBeUndefined();
		expect(button(w, "Deny")).toBeUndefined();

		// Whitespace is not an answer.
		await ta.setValue("   \n\t ");
		await button(w, "Send").trigger("click");
		expect(w.emitted("answer")).toBeUndefined();

		// Real words, emitted verbatim once trimmed — not a token, not a label, not translated.
		await ta.setValue("  delete only T-1, and nothing else  ");
		await button(w, "Send").trigger("click");
		expect(w.emitted("answer")).toEqual([["delete only T-1, and nothing else"]]);
	});

	it("answers nothing when the person backs out", async () => {
		const f = ENGINE.delete_forged_name;
		const w = mountCard({
			question: reactive(engineQuestion(f)),
			tool: f.tool,
		});
		await openOther(w);
		await w.find("textarea").setValue("Approve");
		await button(w, "Cancel").trigger("click");
		await settle();

		// Nothing was answered, and the text is gone rather than left staged behind the buttons.
		expect(w.emitted("answer")).toBeUndefined();
		expect(w.find("textarea").exists()).toBe(false);
		expect(button(w, "Approve")).toBeTruthy();
	});
});
