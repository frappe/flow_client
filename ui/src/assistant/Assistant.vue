<script setup lang="ts">
import { Button } from 'frappe-ui'
import { Sparkles } from 'lucide-vue-next'
import Conversation from './components/Conversation.vue'
import PromptInput from './components/PromptInput.vue'
import type { ComposerSubmit } from './types'
import { useChat } from './useChat'
import './activity.css'

const { messages, streaming, send, reset } = useChat()

const suggestions = [
	'Show revenue for the last 30 days',
	'Which products are trending?',
	'Build me a metric card',
	'Summarize last quarter',
]

function onSubmit(payload: ComposerSubmit) {
	send(payload)
}

// `immediate` slash commands that act on the app rather than the message.
function onCommand(name: string) {
	if (name === 'clear') reset()
	else send({ text: 'What can you help me with?', mentions: [] })
}

function onRegenerate(id: string) {
	// Re-run the previous user turn. Mocked: find the user message before `id`.
	const idx = messages.findIndex((m) => m.id === id)
	const prevUser = [...messages.slice(0, idx)].reverse().find((m) => m.role === 'user')
	const prompt = prevUser?.parts.find((p) => p.type === 'text')
	if (prompt && 'text' in prompt) send(prompt.text)
}
</script>

<template>
	<div class="flex h-full flex-col bg-surface-white">
		<!-- Empty / welcome state -->
		<div v-if="!messages.length" class="flex flex-1 flex-col items-center justify-center px-4">
			<div
				class="flex size-12 items-center justify-center rounded-2xl bg-surface-gray-2 text-ink-gray-7"
			>
				<Sparkles class="size-6" />
			</div>
			<h1 class="mt-4 text-2xl font-semibold text-ink-gray-9">How can I help?</h1>
			<p class="mt-1 text-p-base text-ink-gray-6">
				Ask about your data, or try one of these.
			</p>
			<div class="mt-6 flex max-w-xl flex-wrap justify-center gap-2">
				<Button
					v-for="s in suggestions"
					:key="s"
					class="!rounded-full"
					variant="outline"
					:label="s"
					@click="send(s)"
				/>
			</div>
		</div>

		<!-- Conversation -->
		<Conversation v-else :messages="messages" @regenerate="onRegenerate" />

		<PromptInput :streaming="streaming" @submit="onSubmit" @command="onCommand" />
	</div>
</template>
