<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

// A live activity label: cross-fades when the text changes, shimmers while active,
// and animates its own width so a trailing chevron glides instead of snapping.
const props = defineProps<{ text: string; active?: boolean }>()

const sizer = ref<HTMLSpanElement | null>(null)
const width = ref('auto')

async function measure() {
	await nextTick()
	if (sizer.value) {
		width.value = `${Math.ceil(sizer.value.getBoundingClientRect().width)}px`
	}
}

watch(() => props.text, measure)
onMounted(measure)
</script>

<template>
	<span
		class="label relative inline-grid items-center overflow-hidden whitespace-nowrap"
		:style="{ width }"
	>
		<span
			ref="sizer"
			class="invisible col-start-1 row-start-1 w-fit justify-self-start"
			aria-hidden="true"
		>
			{{ text }}
		</span>
		<Transition name="label">
			<span :key="text" class="col-start-1 row-start-1" :class="active ? 'shimmer' : ''">
				{{ text }}
			</span>
		</Transition>
	</span>
</template>

<style scoped>
.label {
	transition: width 0.25s ease;
}
.label-enter-active,
.label-leave-active {
	transition: opacity 0.25s ease;
}
/* Leaving label goes absolute so it never affects the measured/flow width. */
.label-leave-active {
	position: absolute;
	left: 0;
	top: 0;
}
.label-enter-from,
.label-leave-to {
	opacity: 0;
}
@media (prefers-reduced-motion: reduce) {
	.label,
	.label-enter-active,
	.label-leave-active {
		transition: none;
	}
}
</style>
