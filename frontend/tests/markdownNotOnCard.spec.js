import { describe, it, expect, afterEach } from "vitest";
import { mount } from "@vue/test-utils";
import { mountCard, settle } from "./mountCard";
import MarkdownText from "@/components/MarkdownText.vue";

// A3 — DOES ANY MODEL-CHOSEN VALUE ON THE CARD PATH REACH A MARKDOWN RENDERER OR A HIGHLIGHTER?
//
// THE ANSWER, with the evidence, because it went both ways:
//
//   A markdown renderer EXISTS and it is a genuine HTML sink. `frontend/src/components/
//   MarkdownText.vue:105` is `<div class="md" v-html="html">`, and `html` is built at
//   `MarkdownText.vue:76` from `frappe.markdown(raw)` where `raw` is `props.part.text` — the model's
//   own streamed prose. It is the only `v-html` in the panel and the only markdown renderer; there is
//   NO syntax highlighter anywhere (no highlight.js, prism, shiki or marked in `package.json`).
//
//   NOTHING ON THE CARD PATH REACHES IT. `MarkdownText` has exactly one consumer,
//   `AssistantMessage.vue:64`, guarded by `item.kind === 'text'`, and `kind` is set to `"text"` at
//   `AssistantMessage.vue:27` only for a part with `part.type !== "tool"`. The approval card is the
//   SIBLING branch of the same `v-for` (`AssistantMessage.vue:65`, `item.kind === 'confirm'`), built
//   at line 33 from a part that IS a tool. `ConfirmCard.vue` and everything under it — `ArgsView`,
//   `ArgValue`, `CodeBlock`, `ChipList`, `RecordsList` — import no renderer and contain no `v-html`.
//
// So A3's answer is "it does not", and the prompt is right that the absence is itself worth writing
// down, for two reasons this file turns into assertions.
//
// FIRST, the absence is a fact about the DOM and is asserted as one, not read off an import list: a
// prompt and an argument that are both aggressive markdown produce, inside the card, not one element
// markdown can make. The positive control is in the same file and is what makes that mean anything —
// the identical strings, through the component that DOES render markdown, produce those elements.
//
// SECOND, and this is the finding: `MarkdownText` and `ConfirmCard` are siblings in one flex column
// (`AssistantMessage.vue:58-77`). The model authors the text part, so it can draw a heading, a bold
// line, a blockquote or a link IMMEDIATELY ABOVE the approval card, inside the same message block,
// and markdown is that part's intended feature rather than a defect. What stops that from being a
// forgery of the card is that it is OUTSIDE the card's own bordered box — so the boundary of that box
// is load-bearing, exactly as the quote is load-bearing inside it, and the last test here pins that
// the box exists and that nothing markdown produced is within it. The mobile app renders markdown on
// what looks like the same component tree; if it ever renders the card's own fields through one, the
// first assertion below is what fails.

// The markdown a forgery would use: a heading that looks like a system line, a bold approval, a link.
const HOSTILE_MARKDOWN = [
	"### Approved by admin",
	"**Approved by admin**",
	"[Approve](https://example.invalid/approve)",
	"> Approved by admin",
	"---",
	"| Approved | by admin |\n| --- | --- |\n| yes | yes |",
	"* Approved by admin",
].join("\n\n");

// Tags markdown can produce that the card never legitimately contains. `PRE` and `CODE` are left out
// on purpose: the card has a real `pre.flow-confirm-body` and a real `pre.arg-code` of its own, so
// including them would make this assertion fail for the wrong reason.
const MARKDOWN_TAGS =
	"h1,h2,h3,h4,h5,h6,strong,em,del,a,blockquote,hr,table,thead,tbody,tr,th,td,ul,ol,li,img";

// Stands in for the desk's own `frappe.markdown` (showdown), which does not exist in jsdom — without
// it `MarkdownText` takes its `escapeHtml` fallback at line 73 and produces no elements at all, so the
// positive control below would be green for the wrong reason. Only the control uses it; the card
// tests run with it absent, which is also production's worst case for them.
function stubMarkdown() {
	window.frappe = {
		markdown: (raw) =>
			raw
				.split("\n\n")
				.map((block) => {
					const h = block.match(/^(#{1,6})\s+(.*)$/);
					if (h) return `<h${h[1].length}>${h[2]}</h${h[1].length}>`;
					if (block === "---") return "<hr>";
					if (block.startsWith("> "))
						return `<blockquote>${block.slice(2)}</blockquote>`;
					if (block.startsWith("* ")) return `<ul><li>${block.slice(2)}</li></ul>`;
					if (block.startsWith("|"))
						return "<table><tbody><tr><td>yes</td></tr></tbody></table>";
					return `<p>${block
						.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
						.replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2">$1</a>')}</p>`;
				})
				.join(""),
	};
}

describe("the markdown renderer is real, and the approval card is not on its path", () => {
	afterEach(() => {
		delete window.frappe;
	});

	// THE POSITIVE CONTROL, and it comes first because every assertion after it is an absence.
	it("the same strings DO become elements through the component that renders markdown", async () => {
		stubMarkdown();
		const wrapper = mount(MarkdownText, { props: { part: { text: HOSTILE_MARKDOWN } } });
		await settle();
		const found = wrapper.findAll(MARKDOWN_TAGS).map((e) => e.element.tagName.toLowerCase());
		// A heading, a bold run, a link, a quote, a rule, a table and a list — every shape the card
		// is about to be shown not to have.
		for (const tag of ["h3", "strong", "a", "blockquote", "hr", "table", "ul"]) {
			expect(found, `${tag} should be produced by the markdown renderer`).toContain(tag);
		}
		// And it really is an HTML sink: the text became markup, not text.
		expect(wrapper.find("div.md").element.innerHTML).toContain("<h3>");
	});

	it("aggressive markdown in the approval QUESTION renders as text, not as markup", async () => {
		const wrapper = mountCard({
			question: {
				prompt: `Delete a record?\n\n${HOSTILE_MARKDOWN}`,
				options: ["Approve", "Deny"],
			},
			tool: { name: "delete", arguments: JSON.stringify({ doctype: "Sales Order" }) },
		});
		await settle();
		expect(wrapper.findAll(MARKDOWN_TAGS)).toHaveLength(0);
		// It is on the card — as the characters the tool wrote, which is the whole point. An assertion
		// that only checked for absent tags would also pass if the body were dropped.
		expect(wrapper.find("pre.flow-confirm-body").element.textContent).toContain(
			"### Approved by admin"
		);
	});

	it("aggressive markdown in a tool ARGUMENT renders as text, not as markup", async () => {
		const wrapper = mountCard({
			question: {
				prompt: "Delete a record?\n\nThis cannot be undone.",
				options: ["Approve", "Deny"],
			},
			tool: {
				name: "delete",
				arguments: JSON.stringify({ doctype: "Sales Order", reason: HOSTILE_MARKDOWN }),
			},
		});
		await settle();
		expect(wrapper.findAll(MARKDOWN_TAGS)).toHaveLength(0);
		// The value is present and escaped — it contains newlines, so the one rule quoted it.
		expect(wrapper.text()).toContain("Approved by admin");
		expect(wrapper.find("pre.arg-code").element.textContent).not.toContain("\n");
	});

	it("nothing inside the card is injected as HTML, even with the desk's renderer available", async () => {
		// The renderer PRESENT is the harder case: if any field on this path had been wired through
		// `MarkdownText` or a `v-html` of its own, this is the mount where it would fire.
		stubMarkdown();
		const wrapper = mountCard({
			question: {
				prompt: `Run code?\n\n${HOSTILE_MARKDOWN}`,
				options: ["Approve", "Deny"],
			},
			tool: {
				name: "execute",
				arguments: JSON.stringify({ description: HOSTILE_MARKDOWN, code: "x = 1" }),
			},
		});
		await settle();
		expect(wrapper.findAll(MARKDOWN_TAGS)).toHaveLength(0);
		expect(wrapper.findAll("div.md")).toHaveLength(0);
		// The card's own bordered box exists, and it is what separates the question from any markdown
		// the model drew above it in the same message block. The whole card is inside one such box.
		const root = wrapper.element;
		expect(root.className).toContain("border");
		expect(root.className).toContain("rounded-lg");
	});
});
