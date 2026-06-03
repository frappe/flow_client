<script setup lang="ts">
import { Button } from 'frappe-ui'
import { ArrowUp, Square } from 'lucide-vue-next'
import { ref } from 'vue'
import type { ComposerSubmit } from '../types'
import PromptEditor from './PromptEditor.vue'

const props = defineProps<{ streaming?: boolean }>()
const emit = defineEmits<{
	submit: [payload: ComposerSubmit]
	stop: []
	command: [name: string]
}>()

const text = ref('')
const editorRef = ref<InstanceType<typeof PromptEditor> | null>(null)

function onSubmit(payload: ComposerSubmit) {
	if (props.streaming) return
	emit('submit', payload)
	text.value = '' // clears the editor via PromptEditor's v-model watch
}
</script>

<template>
	<div class="mx-auto w-full max-w-3xl px-4 pb-4">
		<div
			class="flex items-center gap-2 rounded-lg border border-outline-gray-2 bg-surface-white p-2 shadow-sm focus-within:border-outline-gray-3"
		>
			<PromptEditor
				ref="editorRef"
				v-model="text"
				class="flex-1 px-2"
				placeholder="Ask anything…  (@ to reference, / for commands)"
				@submit="onSubmit"
				@command="(name: string) => emit('command', name)"
			/>
			<Button
				v-if="streaming"
				class="shrink-0"
				variant="solid"
				:icon="Square"
				@click="emit('stop')"
			/>
			<Button
				v-else
				class="shrink-0"
				variant="solid"
				:icon="ArrowUp"
				:disabled="!text.trim()"
				@click="editorRef?.submit()"
			/>
		</div>
		<p class="mt-1.5 text-center text-p-xs text-ink-gray-4">
			Mocked responses — no backend connected.
		</p>
	</div>
</template>
