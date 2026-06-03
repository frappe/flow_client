<script setup lang="ts">
import { ChevronRight } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import type { ReasoningPart, ToolPart } from '../types'
import { Collapsible } from '../../base'
import ActivityDetail from './ActivityDetail.vue'
import ActivityLabel from './ActivityLabel.vue'
import ActivityStep from './ActivityStep.vue'

// A chain of pre-answer activity: reasoning + tool/skill calls, in order. Always
// one collapsible: a single step expands straight to its detail, multiple steps
// expand to a timeline. Keeping one header avoids a DOM swap as the chain grows.
const props = defineProps<{ parts: Array<ReasoningPart | ToolPart> }>()

const isToolRunning = (p: ReasoningPart | ToolPart) =>
	p.type === 'tool' && (p.status === 'pending' || p.status === 'running')
const isThinking = (p: ReasoningPart | ToolPart) => p.type === 'reasoning' && !!p.streaming

const running = computed(() => props.parts.some((p) => isToolRunning(p) || isThinking(p)))
const toolCount = computed(() => props.parts.filter((p) => p.type === 'tool').length)
const single = computed(() => props.parts.length === 1)

const stepLabel = (p: ReasoningPart | ToolPart) =>
	p.type === 'reasoning' ? 'Thought process' : p.label || p.name

// While running, surface the active step; once done, summarize the whole chain.
const summary = computed(() => {
	if (running.value) {
		const active = props.parts.find((p) => isToolRunning(p) || isThinking(p))
		if (!active) return 'Working…'
		return active.type === 'reasoning' ? 'Thinking…' : active.label || active.name
	}
	// A single step keeps its own name; a chain summarizes its tool count.
	if (single.value) return stepLabel(props.parts[0])
	const n = toolCount.value
	return n > 0 ? `Ran ${n} ${n === 1 ? 'step' : 'steps'}` : 'Thought process'
})

// Collapsed by default: while running we show only the live changing label;
// expanding reveals the step detail (single) or the timeline (multiple).
const open = ref(false)
</script>

<template>
	<Collapsible v-model:open="open" class="my-1">
		<template #trigger="{ open: isOpen }">
			<button
				class="flex items-center gap-1.5 text-p-sm text-ink-gray-5 transition-colors"
				:class="{ 'hover:text-ink-gray-7': !running }"
			>
				<ActivityLabel :text="summary" :active="running" />
				<ChevronRight
					class="mt-0.5 size-3.5 transition-transform"
					:class="{ 'rotate-90': isOpen }"
				/>
			</button>
		</template>

		<!-- Single step: its detail directly. Multiple: a connected timeline. -->
		<ActivityDetail v-if="single" :part="parts[0]" class="mt-1.5" />
		<div v-else class="relative mt-1.5">
			<span
				class="absolute bottom-2.5 left-[7px] top-2.5 w-px bg-surface-gray-3"
				aria-hidden="true"
			/>
			<ActivityStep v-for="(part, i) in parts" :key="i" :part="part" />
		</div>
	</Collapsible>
</template>
