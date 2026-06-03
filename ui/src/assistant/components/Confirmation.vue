<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, inject, onBeforeUnmount, onMounted } from 'vue'
import type { ConfirmationPart } from '../types'
import { Card } from '../../base'
import { RESPOND_CONFIRMATION } from '../useChat'

// A side-effectful action awaiting approval. Active: a card with data-driven
// buttons. Resolved (part.decision set): a compact one-line row, matching how
// activity/tool calls collapse.
const props = defineProps<{ part: ConfirmationPart }>()

// Provided by useChat — keeps parts serializable (no callback embedded in data).
const respond = inject(RESPOND_CONFIRMATION)

const resolved = computed(() => props.part.decision !== undefined)
const startChoices = computed(() => props.part.choices.filter((c) => c.align === 'start'))
const endChoices = computed(() => props.part.choices.filter((c) => c.align !== 'start'))
const primary = computed(() => props.part.choices.find((c) => c.primary))
const denyChoice = computed(
	() => props.part.choices.find((c) => c.value === 'deny') ?? startChoices.value[0],
)

const chosen = computed(() => props.part.choices.find((c) => c.value === props.part.decision))

function decide(value: string) {
	if (resolved.value) return
	respond?.(props.part.id, value)
}

// While pending, ⌘/Ctrl+↵ confirms the primary action and Esc denies.
function onKey(e: KeyboardEvent) {
	if (resolved.value) return
	if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && primary.value) {
		e.preventDefault()
		decide(primary.value.value)
	} else if (e.key === 'Escape' && denyChoice.value) {
		e.preventDefault()
		decide(denyChoice.value.value)
	}
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
	<!-- Resolved: compact summary row, flush-left to match the activity labels -->
	<div v-if="resolved" class="text-p-sm text-ink-gray-5">
		{{ chosen?.label ?? 'Resolved' }}
		<span v-if="part.target" class="text-ink-gray-4">· {{ part.target }}</span>
	</div>

	<!-- Active: the confirmation card -->
	<Card v-else>
		<p class="text-p-base font-semibold text-ink-gray-9">{{ part.title }}</p>

		<div class="mt-2 space-y-1.5">
			<p v-if="part.target" class="text-p-sm text-ink-gray-7">{{ part.target }}</p>
			<p v-if="part.reason" class="text-p-sm text-ink-gray-6">{{ part.reason }}</p>
			<pre
				v-if="part.detail"
				class="overflow-x-auto rounded bg-surface-gray-2 px-2 py-1.5 text-p-xs text-ink-gray-7"
				>{{ part.detail }}</pre
			>
		</div>

		<div class="mt-3 flex items-center justify-between gap-2">
			<div class="flex gap-2">
				<Button
					v-for="c in startChoices"
					:key="c.value"
					:variant="c.variant ?? 'subtle'"
					:theme="c.theme ?? 'gray'"
					:label="c.label"
					@click="decide(c.value)"
				/>
			</div>
			<div class="flex gap-2">
				<Button
					v-for="c in endChoices"
					:key="c.value"
					:variant="c.variant ?? 'outline'"
					:theme="c.theme ?? 'gray'"
					@click="decide(c.value)"
				>
					<span class="flex items-center gap-1.5">
						{{ c.label }}
					</span>
				</Button>
			</div>
		</div>
	</Card>
</template>
