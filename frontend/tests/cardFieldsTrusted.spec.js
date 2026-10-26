import { describe, it, expect } from "vitest";
import { mountCard, settle } from "./mountCard";
import { toolLabel, blockKeysFor, humanize } from "@/lib/toolMeta";

// A4 — THE FIELDS NOBODY CHECKED: the tool NAME.
//
// Run 14 (`30ccad4`) closed the argument path: every value and every argument KEY on the card goes
// through `lib/display.js`. It did not ask the same question of the tool NAME, and the name is as
// model-chosen as the arguments are — it is a field of the tool call the model emitted, and nothing
// on the way to the panel restricts it to a tool that exists. `store.js` builds a part for whatever
// name arrived, and `ActivityStep`/`ConfirmCard` render it.
//
// The name is then used as an INDEX into two plain object literals: `LABELS` in `toolLabel`
// (`toolMeta.js:56`) and `CODE_ARG_KEYS` in `blockKeysFor` (`toolMeta.js:171`). A plain object
// inherits from `Object.prototype`, so eight names the model can choose resolve to a member of that
// prototype instead of missing:
//
//   `LABELS["constructor"]`  -> the `Object` function, TRUTHY, so `toolLabel` takes the
//                               `__(LABELS[name])` branch and the headline reads
//                               `function Object() { [native code] }`. The escaping branch —
//                               `humanize(name)`, the only one that displays the real name — is
//                               never reached. The card names something that is not what will run.
//   `CODE_ARG_KEYS["__proto__"]` -> `Object.prototype`, TRUTHY, so `blockKeysFor` returns it instead
//                               of an empty Set, and `ArgValue`'s `props.codeKeys.has(k)` throws
//                               `codeKeys.has is not a function` INSIDE A COMPUTED DURING RENDER.
//                               That is the MEDIUM 2 shape run 14 fixed at `16d5ace`, from a
//                               direction nothing guarded: not a degraded card but NO card, and so
//                               an approval that cannot be answered. A model that does not want to
//                               be denied can reach it by choosing a tool name.
//
// Both assertions below are about the SAFE outcome, so this file run against the unfixed source IS
// the measurement.
const PROTOTYPE_NAMES = [
	"__proto__",
	"constructor",
	"toString",
	"valueOf",
	"hasOwnProperty",
	"isPrototypeOf",
	"propertyIsEnumerable",
	"toLocaleString",
];

describe("a model-chosen tool name cannot reach Object.prototype", () => {
	// The positive control for the whole file: these names DO resolve on a plain object literal, so a
	// green below is a fact about the fix and not about the names being harmless. Without this, a
	// typo in the list would make every test pass for the wrong reason.
	it("the names in this list really are inherited members of a plain object", () => {
		const plain = { execute: "Executing" };
		const resolved = PROTOTYPE_NAMES.filter((n) => plain[n] !== undefined);
		expect(resolved).toEqual(PROTOTYPE_NAMES);
	});

	it.each(PROTOTYPE_NAMES)("blockKeysFor(%j) is a real, empty Set", (name) => {
		const keys = blockKeysFor(name);
		// `.has` must be callable: this is the assertion that the card renders at all.
		expect(typeof keys.has).toBe("function");
		// And it must claim nothing: only a tool's own declaration earns raw rendering, and a tool
		// named `__proto__` has declared nothing.
		expect(keys.has("code")).toBe(false);
		expect(keys.has("anything")).toBe(false);
	});

	it.each(PROTOTYPE_NAMES)(
		"toolLabel(%j) shows the name, escaped, not a prototype member",
		(name) => {
			const label = toolLabel(name);
			expect(label).not.toContain("native code");
			expect(label).not.toContain("[object ");
			// The one right answer: the same thing every other unknown tool name gets.
			expect(label).toBe(humanize(name));
		}
	);

	it("the ordinary names are untouched — the control that these tests are not vacuous", () => {
		expect(toolLabel("execute")).toBe("Executing");
		expect(toolLabel("find_doctypes")).toBe("Finding relevant DocTypes");
		expect(toolLabel("my_custom_tool")).toBe("My custom tool");
		// `execute`'s declaration still works, or the fix would have closed the hole by removing the
		// feature the hole was in.
		expect(blockKeysFor("execute").has("code")).toBe(true);
		expect(blockKeysFor("execute").has("description")).toBe(false);
		expect(blockKeysFor("read").has("code")).toBe(false);
	});
});

describe("the approval card survives a prototype-named tool", () => {
	it.each(PROTOTYPE_NAMES)("a call named %j still draws an answerable card", async (name) => {
		const wrapper = mountCard({
			question: {
				prompt: `Run a tool?\n\nIt wants to run "${name}".`,
				options: ["Approve", "Deny"],
			},
			tool: {
				name,
				arguments: JSON.stringify({ doctype: "Sales Order", code: "x = 1\ny = 2" }),
			},
		});
		await settle();
		// The approval is answerable: the three buttons exist and act.
		const labels = wrapper.findAll("button").map((b) => b.text());
		expect(labels).toEqual(["Approve", "Deny", "Other…"]);
		// And nothing on it is a prototype member read aloud.
		const text = wrapper.text();
		expect(text).not.toContain("native code");
		expect(text).not.toContain("[object ");
		// The `code` argument is NOT raw: this tool declared nothing, so its multi-line value is
		// escaped like any other model-chosen value. One unescaped newline here would be the
		// forgery run 14 closed, re-opened through the name.
		const pre = wrapper.find("pre.arg-code");
		if (pre.exists()) expect(pre.text()).not.toContain("\n");
	});
});
