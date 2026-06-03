<script setup lang="ts">
import { Brain, ChevronRight, LoaderCircle, Sparkles, Terminal } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import type { ReasoningPart, ToolPart } from '../types'
import { Collapsible } from '../../base'
import ActivityDetail from './ActivityDetail.vue'
import ActivityLabel from './ActivityLabel.vue'

// One node in a group's activity timeline — a reasoning block or a tool/skill call.
const props = defineProps<{ part: ReasoningPart | ToolPart }>()

const active = computed(() =>
	props.part.type === 'reasoning'
		? !!props.part.streaming
		: props.part.status === 'pending' || props.part.status === 'running',
)

const icon = computed(() => {
	// Active steps all share the spinner; idle steps show their type icon.
	if (active.value) return LoaderCircle
	if (props.part.type === 'reasoning') return Brain
	return props.part.kind === 'skill' ? Sparkles : Terminal
})

const iconClass = computed(() => ({ 'animate-spin': active.value }))

const label = computed(() => {
	if (props.part.type === 'reasoning')
		return props.part.streaming ? 'Thinking…' : 'Thought process'
	return props.part.label || props.part.name
})

const isError = computed(() => props.part.type === 'tool' && props.part.status === 'error')

// Reasoning always expands to its text; a tool expands only when it has I/O.
const hasDetail = computed(() =>
	props.part.type === 'reasoning'
		? true
		: props.part.input !== undefined || props.part.output !== undefined,
)

const open = ref(false)
</script>

<template>
	<div class="relative py-1 pl-5">
		<!-- Per-node icon, masking the connector so the line reads as linking nodes. -->
		<span
			class="absolute left-0 top-1 flex w-3.5 justify-center bg-surface-white py-0.5 text-ink-gray-4"
			aria-hidden="true"
		>
			<component :is="icon" class="size-3.5" :class="iconClass" />
		</span>

		<Collapsible v-if="hasDetail" v-model:open="open">
			<template #trigger>
				<button
					class="flex w-full items-center gap-1.5 text-left text-p-sm text-ink-gray-6 transition-colors hover:text-ink-gray-8"
				>
					<ActivityLabel
						:text="label"
						:active="active"
						:class="{ 'text-ink-red-3': isError }"
					/>
					<ChevronRight
						class="mt-0.5 size-3.5 shrink-0 text-ink-gray-4 transition-transform"
						:class="{ 'rotate-90': open }"
					/>
				</button>
			</template>

			<ActivityDetail :part="part" class="mb-1.5 mt-1" />
		</Collapsible>

		<ActivityLabel v-else :text="label" :active="active" class="text-p-sm text-ink-gray-6" />
	</div>
</template>
