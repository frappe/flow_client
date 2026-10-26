import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import ConfirmCard from "@/components/ConfirmCard.vue";

// The runner's own proof of life. If this file cannot mount an SFC and read text out of a real DOM,
// nothing else in this directory means anything, so it is the first thing that has to go red on
// demand and then green.
describe("the runner", () => {
	it("mounts the real component and reads rendered text out of the DOM", () => {
		const w = mount(ConfirmCard, {
			props: {
				question: { prompt: "Approve this?\n\nDelete 1 Sales Invoice record", options: ["Approve", "Deny"] },
				tool: { name: "delete", arguments: { doctype: "Sales Invoice", names: ["SI-0001"] } },
			},
		});
		// Rendered, not source: the component file contains "{{ title }}", never this string.
		expect(w.text()).toContain("Delete 1 Sales Invoice record");
	});
});
