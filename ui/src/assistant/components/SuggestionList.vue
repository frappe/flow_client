<script setup lang="ts">
import type { Component } from 'vue'
import { nextTick, onBeforeUpdate, ref, watch } from 'vue'

// The popup rendered by both the `@` and `/` tiptap suggestions. It's purely
// presentational: tiptap drives it with `items` + a `command(item)` callback,
// and reads back keyboard handling via the exposed `onKeyDown`. Modeled on
// frappe-ui's SuggestionList so we stay on the standard contract.
interface ListItem {
	label?: string
	title?: string
	name?: string
	sublabel?: string
	description?: string
	// Group header (consecutive items sharing a type render under one heading).
	type?: string
	icon?: Component
}

const props = defineProps<{
	items: ListItem[]
	command: (item: ListItem) => void
}>()

const selectedIndex = ref(0)
const itemRefs = ref<HTMLButtonElement[]>([])
onBeforeUpdate(() => (itemRefs.value = []))

// Reset the highlight whenever the filtered list changes.
watch(
	() => props.items,
	() => (selectedIndex.value = 0),
)

const labelOf = (i: ListItem) => i.label || i.title || i.name || ''
const subOf = (i: ListItem) => i.sublabel || i.description
const showHeader = (i: number) =>
	!!props.items[i].type && props.items[i].type !== props.items[i - 1]?.type

function select(index: number) {
	const item = props.items[index]
	if (item) props.command(item)
}

function scrollIntoView() {
	nextTick(() => itemRefs.value[selectedIndex.value]?.scrollIntoView({ block: 'nearest' }))
}

function onKeyDown({ event }: { event: KeyboardEvent }): boolean {
	if (!props.items.length) return false
	if (event.key === 'ArrowUp') {
		selectedIndex.value = (selectedIndex.value + props.items.length - 1) % props.items.length
		scrollIntoView()
		return true
	}
	if (event.key === 'ArrowDown') {
		selectedIndex.value = (selectedIndex.value + 1) % props.items.length
		scrollIntoView()
		return true
	}
	if (event.key === 'Enter') {
		select(selectedIndex.value)
		return true
	}
	return false
}

defineExpose({ onKeyDown })
</script>

<template>
	<div
		v-if="items.length"
		class="max-h-72 min-w-56 overflow-y-auto rounded-lg border border-outline-gray-1 bg-surface-white p-1 shadow-lg"
	>
		<template v-for="(item, i) in items" :key="i">
			<p
				v-if="showHeader(i)"
				class="px-2 pb-1 pt-2 text-p-xs font-medium uppercase tracking-wide text-ink-gray-5"
			>
				{{ item.type }}
			</p>
			<button
				:ref="
					(el) => {
						if (el) itemRefs[i] = el as HTMLButtonElement
					}
				"
				class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors"
				:class="i === selectedIndex ? 'bg-surface-gray-3' : ''"
				@click="select(i)"
				@mouseover="selectedIndex = i"
			>
				<component
					:is="item.icon"
					v-if="item.icon"
					class="size-4 shrink-0 text-ink-gray-5"
				/>
				<span class="min-w-0 flex-1">
					<span class="block truncate text-p-sm text-ink-gray-8">{{
						labelOf(item)
					}}</span>
					<span v-if="subOf(item)" class="block truncate text-p-xs text-ink-gray-5">{{
						subOf(item)
					}}</span>
				</span>
			</button>
		</template>
	</div>
</template>
