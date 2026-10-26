import { mount } from "@vue/test-utils";
import { nextTick } from "vue";
import ConfirmCard from "@/components/ConfirmCard.vue";

// Every test in this directory mounts through here, for one reason that is easy to get wrong and
// silently fatal:
//
// The panel's CSS is run through `postcss-prefix-selector` (see `postcss.config.js`), so EVERY rule
// ships as `#flow-root .flow-confirm-body[data-v-…]` — the desk loads the bundle into its own <head>
// and the prefix is what stops frappe-ui's preflight bleeding onto the surrounding page. In
// production the card is therefore always inside `#flow-root` (`main.js` creates
// `div#flow-root` and mounts the app into it).
//
// A plain `mount()` attaches to a bare `document.body`, so NONE of those rules match, and
// `getComputedStyle` answers "" for every property the stylesheet sets. A height-cap assertion
// written against that mount would read `maxHeight === ""` and pass whatever the stylesheet said —
// a green that means "no CSS was applied at all". So the container is part of the fixture.
export function mountCard(props) {
	const host = document.createElement("div");
	host.id = "flow-root";
	document.body.appendChild(host);
	return mount(ConfirmCard, { attachTo: host, props });
}

// `onMounted` defers the scroll into a `nextTick`; two ticks lets it land.
export async function settle() {
	await nextTick();
	await nextTick();
}

// The engine composes an approval question as one head line, a blank line, then the tool's body.
// `flow/tools/builtins.py` is what writes it; these helpers build the same shape so a test states
// what the engine produces rather than a hand-made string that resembles it.
export function approval(prompt, tool = null) {
	return { question: { prompt, options: ["Approve", "Deny"] }, tool };
}

// Every field the ENGINE puts on a Question, carried in as the engine set it — and deliberately by
// spread, so a field added to the Question later arrives here without anyone remembering to add it.
//
// Run 13's MEDIUM 8: the specs built `{ prompt, options }` by hand and dropped the rest, and the card
// BRANCHES on one of the fields they dropped — `allow_other !== false` is what draws the free-text
// affordance. Two tests prove that affordance exists; built from two fields, both stayed green through
// an engine that stopped allowing free text, proving something production no longer shows. The fixture
// guard (`flow/tests/test_s21_card_fixture_is_current.py`) now captures `allow_other` for every case,
// so with the spread in place an engine-side flip reddens the tests instead of hiding inside them.
export function engineQuestion(f) {
	const { tool, ...question } = f;
	return question;
}
