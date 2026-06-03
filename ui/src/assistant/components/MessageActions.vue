<script setup lang="ts">
import { Button } from 'frappe-ui'
import { Check, Copy, RefreshCw, ThumbsDown, ThumbsUp } from 'lucide-vue-next'
import { ref } from 'vue'

const props = defineProps<{ text: string }>()
const emit = defineEmits<{ regenerate: [] }>()

const copied = ref(false)
function copy() {
	navigator.clipboard.writeText(props.text)
	copied.value = true
	setTimeout(() => (copied.value = false), 1500)
}
</script>

<template>
	<div class="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
		<Button
			variant="ghost"
			:icon="copied ? Check : Copy"
			:tooltip="copied ? 'Copied' : 'Copy'"
			@click="copy"
		/>
		<Button
			variant="ghost"
			:icon="RefreshCw"
			tooltip="Regenerate"
			@click="emit('regenerate')"
		/>
		<Button variant="ghost" :icon="ThumbsUp" tooltip="Good response" />
		<Button variant="ghost" :icon="ThumbsDown" tooltip="Bad response" />
	</div>
</template>
