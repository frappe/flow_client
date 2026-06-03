<script setup lang="ts">
import { TrendingDown, TrendingUp } from 'lucide-vue-next'
import { computed } from 'vue'

const props = defineProps<{
	label: string
	value: string
	delta?: string
	trend?: 'up' | 'down'
}>()

const isUp = computed(() => props.trend !== 'down')
</script>

<template>
	<div class="w-full max-w-xs rounded-lg border border-outline-gray-2 bg-surface-white p-4">
		<p class="text-p-sm text-ink-gray-6">{{ label }}</p>
		<p class="mt-1 text-2xl font-semibold text-ink-gray-9">{{ value }}</p>
		<div
			v-if="delta"
			class="mt-1 flex items-center gap-1 text-p-sm"
			:class="isUp ? 'text-ink-green-3' : 'text-ink-red-3'"
		>
			<component :is="isUp ? TrendingUp : TrendingDown" class="size-3.5" />
			<span>{{ delta }}</span>
		</div>
	</div>
</template>
