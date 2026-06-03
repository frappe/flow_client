<script setup lang="ts">
import { computed } from 'vue'
import type { MessagePart, ReasoningPart, ToolPart } from '../types'
import { widgetRegistry } from '../widgets/registry'
import ActivityGroup from './ActivityGroup.vue'
import Confirmation from './Confirmation.vue'
import Markdown from './Markdown.vue'

const props = defineProps<{ parts: MessagePart[] }>()

// Reasoning and tool/skill calls are all "activity" — they form one pre-answer
// chain, broken only by answer text (or a widget). ActivityGroup renders a chain:
// a single step on its own, or multiple steps under one collapsible summary.
type Activity = ReasoningPart | ToolPart
type RenderItem = { kind: 'part'; part: MessagePart } | { kind: 'activity'; parts: Activity[] }

const items = computed<RenderItem[]>(() => {
	const out: RenderItem[] = []
	for (const part of props.parts) {
		const last = out[out.length - 1]
		if (part.type === 'reasoning' || part.type === 'tool') {
			if (last?.kind === 'activity') last.parts.push(part)
			else out.push({ kind: 'activity', parts: [part] })
		} else {
			out.push({ kind: 'part', part })
		}
	}
	return out
})
</script>

<template>
	<template v-for="(item, i) in items" :key="i">
		<ActivityGroup v-if="item.kind === 'activity'" :parts="item.parts" />
		<template v-else>
			<Confirmation v-if="item.part.type === 'confirmation'" :part="item.part" />
			<Markdown v-else-if="item.part.type === 'text'" :content="item.part.text" />
			<component
				v-else-if="item.part.type === 'widget' && widgetRegistry[item.part.component]"
				:is="widgetRegistry[item.part.component]"
				v-bind="item.part.props"
			/>
			<p v-else-if="item.part.type === 'widget'" class="text-p-sm text-ink-red-3">
				Unknown widget: {{ item.part.component }}
			</p>
		</template>
	</template>
</template>
