<template>
	<CollapsibleRoot v-model:open="open" :disabled="props.disabled" data-slot="root">
		<CollapsibleTrigger as-child data-slot="trigger">
			<slot name="trigger" :open="open" />
		</CollapsibleTrigger>
		<CollapsibleContent class="collapsible-content" data-slot="content">
			<slot />
		</CollapsibleContent>
	</CollapsibleRoot>
</template>

<script setup lang="ts">
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from 'reka-ui'
import type { CollapsibleProps } from './types'

const props = withDefaults(defineProps<CollapsibleProps>(), {
	disabled: false,
})

/** Whether the panel is expanded. Two-way bindable; defaults to closed. */
const open = defineModel<boolean>('open', { default: false })

defineSlots<{
	/** The element that toggles the panel. Receives `{ open }` (P7). */
	trigger?: (props: { open: boolean }) => any
	/** The collapsible panel content. */
	default?: () => any
}>()
</script>

<style scoped>
/* reka-ui exposes the measured panel height as a CSS var, enabling a smooth
   height transition without JS. */
.collapsible-content {
	overflow: hidden;
}
.collapsible-content[data-state='open'] {
	animation: collapsible-down 150ms ease-out;
}
.collapsible-content[data-state='closed'] {
	animation: collapsible-up 150ms ease-out;
}
@keyframes collapsible-down {
	from {
		height: 0;
	}
	to {
		height: var(--reka-collapsible-content-height);
	}
}
@keyframes collapsible-up {
	from {
		height: var(--reka-collapsible-content-height);
	}
	to {
		height: 0;
	}
}
@media (prefers-reduced-motion: reduce) {
	.collapsible-content[data-state='open'],
	.collapsible-content[data-state='closed'] {
		animation: none;
	}
}
</style>
