<script setup lang="ts">
import { Button } from 'frappe-ui'
import { ArrowDown } from 'lucide-vue-next'
import { nextTick, onMounted, ref, watch } from 'vue'
import type { Message } from '../types'
import MessageItem from './Message.vue'

const props = defineProps<{ messages: Message[] }>()
defineEmits<{ regenerate: [id: string] }>()

const scroller = ref<HTMLElement>()
const atBottom = ref(true)

function onScroll() {
	const el = scroller.value
	if (!el) return
	atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function scrollToBottom(smooth = true) {
	const el = scroller.value
	if (!el) return
	el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
}

// Follow new content only when the user is already pinned to the bottom.
watch(
	() => props.messages.map((m) => m.parts.length).join(','),
	() => atBottom.value && nextTick(() => scrollToBottom()),
	{ flush: 'post' },
)

onMounted(() => scrollToBottom(false))
</script>

<template>
	<div class="relative flex-1 overflow-hidden">
		<div ref="scroller" class="h-full overflow-y-auto" @scroll="onScroll">
			<div class="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
				<MessageItem
					v-for="m in messages"
					:key="m.id"
					:message="m"
					@regenerate="$emit('regenerate', m.id)"
				/>
			</div>
		</div>

		<Transition
			enter-active-class="transition"
			enter-from-class="opacity-0 translate-y-1"
			leave-active-class="transition"
			leave-to-class="opacity-0 translate-y-1"
		>
			<Button
				v-if="!atBottom"
				class="absolute bottom-4 left-1/2 -translate-x-1/2 !rounded-full shadow-sm"
				variant="outline"
				:icon="ArrowDown"
				@click="scrollToBottom()"
			/>
		</Transition>
	</div>
</template>
