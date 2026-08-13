<script setup>
import { FeatherIcon } from "@/lib/ui";
import { __ } from "@/lib/translate";

defineProps({
	message: { type: String, required: true },
});
</script>

<template>
	<div class="flow-error-box my-2.5 rounded-xl border border-red-200 bg-red-50 p-3.5 text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
		<div class="flex items-center gap-2 mb-1.5 font-medium text-xs text-red-700 dark:text-red-300">
			<FeatherIcon name="alert-triangle" class="h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
			<span>{{ __("Error") }}</span>
		</div>
		<pre class="m-0 max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-red-800 dark:text-red-200">{{ message }}</pre>
	</div>
</template>

<style scoped>
.flow-error-box {
	background-color: var(--surface-red-1, #fef2f2);
	border-color: var(--border-red-2, #fecaca);
	color: var(--ink-red-4, #991b1b);
}
.flow-error-box pre {
	color: var(--ink-red-4, #991b1b);
	font-family: var(--font-stack-monospace, ui-monospace, monospace);
}
</style>
