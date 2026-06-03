<script setup lang="ts">
import { computed } from 'vue'
import type { Message } from '../types'
import { TOKEN_CLASS } from '../tokenClass'
import MessageActions from './MessageActions.vue'
import MessageParts from './MessageParts.vue'

const props = defineProps<{ message: Message }>()
defineEmits<{ regenerate: [] }>()

const isUser = computed(() => props.message.role === 'user')

// Concatenated text of the message, for the copy action.
const plainText = computed(() =>
	props.message.parts
		.filter((p) => p.type === 'text')
		.map((p) => (p as { text: string }).text)
		.join('\n\n'),
)
</script>

<template>
	<div class="group" :class="isUser ? 'flex justify-end' : ''">
		<!-- User: quiet bubble on the right. Assistant: flush, full width. -->
		<div
			v-if="isUser"
			class="max-w-[80%] rounded-xl bg-surface-gray-2 px-4 py-2.5 text-ink-gray-8"
		>
			<span v-if="message.command" :class="TOKEN_CLASS" class="mr-1"
				>/{{ message.command }}</span
			>
			<MessageParts :parts="message.parts" />
		</div>
		<div v-else class="min-w-0 flex flex-col gap-2">
			<MessageParts :parts="message.parts" />
			<MessageActions
				v-if="!message.streaming"
				:text="plainText"
				@regenerate="$emit('regenerate')"
			/>
		</div>
	</div>
</template>
