<script setup>
import { ref, computed } from "vue";
import { __ } from "@/lib/translate";
import { displayText } from "@/lib/display";

// Code with a line-preview toggle.
//
// This `<pre>` is `white-space: pre-wrap`, so it is the one element on the approval card where a
// newline in a value draws a REAL second line. That is exactly what code needs and exactly what a
// model-chosen value must not have, so the two are told apart by `raw`.
//
// THE RULE, stated here because this is the only place it is acted on: a value renders as raw,
// multi-line text when — and only when — the TOOL'S OWN DECLARATION says that argument is code.
// That declaration is `CODE_ARG_KEYS` in `lib/toolMeta.js` (`execute` -> `code`): a static table in
// reviewed client code, keyed by tool name and argument name, which no model output can reach. The
// SHAPE of a value never earns it the right to be rendered raw — a value the model made multi-line
// so that `isBlockText` would route it to a code block is still a value the model chose, and is
// escaped. Code the approver asked to see is raw; a value the model picked is text.
const props = defineProps({
	code: { type: String, default: "" },
	raw: { type: Boolean, default: false },
});

const PREVIEW_LINES = 4;

const text = computed(() => (props.raw ? props.code : displayText(props.code)));
const lines = computed(() => text.value.split("\n"));
const hasMore = computed(() => lines.value.length > PREVIEW_LINES);
const expanded = ref(false);
const shown = computed(() =>
	hasMore.value && !expanded.value ? lines.value.slice(0, PREVIEW_LINES).join("\n") : text.value
);
</script>

<template>
	<div>
		<pre class="arg-code">{{ shown }}</pre>
		<button
			v-if="hasMore"
			class="mt-1 text-xs text-ink-gray-5 hover:text-ink-gray-7"
			@click="expanded = !expanded"
		>
			{{
				expanded
					? __("Show less")
					: __("Show {0} more lines", [lines.length - PREVIEW_LINES])
			}}
		</button>
	</div>
</template>

<style scoped>
.arg-code {
	margin: 0;
	max-height: 320px;
	overflow: auto;
	white-space: pre-wrap;
	word-break: break-word;
	border-radius: 8px;
	background: var(--surface-gray-2);
	padding: 8px 10px;
	font-family: var(--font-stack-monospace, ui-monospace, monospace);
	font-size: 12.5px;
	line-height: 1.6;
	color: var(--ink-gray-8);
}
</style>
