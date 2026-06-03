<script setup lang="ts">
// A plain surface container: 16px padding (p-4), 8px radius (rounded-lg), a 1px
// border (#ededed = outline-gray-1, frappe-ui's default border color), no shadow.
// The root `class` falls through, so callers can layer on a background etc.
</script>

<template>
	<div class="rounded-lg border border-outline-gray-1 p-4">
		<slot />
	</div>
</template>
