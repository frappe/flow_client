<script setup lang="ts">
import type { ReasoningPart, ToolPart } from '../types'

// The expanded body of an activity: a reasoning block's thought, or a tool's I/O.
// Reused by ActivityStep (inside a timeline) and ActivityGroup (single-step case).
const props = defineProps<{ part: ReasoningPart | ToolPart }>()

const format = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v, null, 2))
</script>

<template>
	<p v-if="part.type === 'reasoning'" class="text-p-sm text-ink-gray-5">{{ part.text }}</p>
	<div
		v-else
		class="flex max-h-40 flex-col items-start gap-2 overflow-auto rounded border bg-surface-white p-2 text-p-xs text-ink-gray-7"
	>
		<div v-if="part.input" class="w-full max-w-full rounded bg-surface-gray-2 px-2 py-1.5">
			<p class="mb-1">Input</p>
			<pre class="overflow-x-auto">{{ format(part.input) }}</pre>
		</div>
		<div
			v-if="part.output !== undefined"
			class="w-full max-w-full rounded bg-surface-gray-2 px-2 py-1.5"
		>
			<p class="mb-1">Output</p>
			<pre class="overflow-x-auto">{{ format(part.output) }}</pre>
		</div>
	</div>
</template>
