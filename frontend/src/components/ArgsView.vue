<script setup>
import { computed } from "vue";
import { parseArgs, rawArgs } from "@/lib/toolMeta";
import ArgValue from "./ArgValue.vue";
import CodeBlock from "./CodeBlock.vue";

// Entry point for a tool call's arguments: parses once, renders by shape.
// Unparseable JSON falls back to the raw payload so it's never hidden.
// `blockKeys` is a LAYOUT decision — which fields render as a full-width block — and `RecordsList`
// derives it from the values it was given, so it is not a statement about trust. `codeKeys` is the
// tool's own declaration that an argument IS code, which is what earns raw, multi-line rendering.
// They are separate props because conflating them is how a model-chosen value would inherit the one
// exemption on this surface. See `CodeBlock.vue` for the rule.
const props = defineProps({
	arguments: { default: null },
	blockKeys: { type: Object, default: () => new Set() },
	codeKeys: { type: Object, default: () => new Set() },
});

const parsed = computed(() => parseArgs(props.arguments));
const hasFields = computed(() => Object.keys(parsed.value).length > 0);
const raw = computed(() => (hasFields.value ? "" : rawArgs(props.arguments)));
</script>

<template>
	<ArgValue v-if="hasFields" :value="parsed" :block-keys="blockKeys" :code-keys="codeKeys" />
	<!-- An unparseable payload is the model's own bytes, shown rather than hidden. It is not code the
	     approver asked for, so it is escaped: `raw` stays false. -->
	<CodeBlock v-else-if="raw" :code="raw" />
</template>
