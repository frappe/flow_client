<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import { computed } from 'vue'

const props = defineProps<{ content: string }>()

const md = new MarkdownIt({
	html: false,
	linkify: true,
	breaks: true,
	highlight(code, lang) {
		if (lang && hljs.getLanguage(lang)) {
			return `<pre class="hljs-pre"><code>${
				hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
			}</code></pre>`
		}
		return `<pre class="hljs-pre"><code>${hljs.highlightAuto(code).value}</code></pre>`
	},
})

const html = computed(() => md.render(props.content || ''))
</script>

<template>
	<div
		class="prose-chat prose prose-sm max-w-none text-ink-gray-8 prose-code:font-normal prose-code:before:content-none prose-code:after:content-none prose-a:text-ink-blue-3"
		v-html="html"
	/>
</template>

<style>
@import 'frappe-ui/hljs-theme.css';
</style>

<style scoped>
/* Tailwind Typography's margins are tuned for articles and read uneven in a
   chat bubble. Mirror frappe-ui's TextEditor `.prose-v2`: normalize the
   plugin's per-element margins and impose one uniform inter-block rhythm.
   `:where(...)` keeps these low-specificity but the scoped `.prose-chat` class
   still beats the plugin's own `:where()` rules. */
.prose-chat {
	line-height: 1.6;
}
.prose-chat :deep(:where(p, ul, ol, pre, blockquote, h1, h2, h3, h4, h5, h6, table)) {
	margin-top: 0;
	margin-bottom: 0.6rem;
}
.prose-chat :deep(:where(p, ul, ol, pre, blockquote, h1, h2, h3, h4, h5, h6, table):last-child) {
	margin-bottom: 0;
}
.prose-chat :deep(li) {
	margin-top: 0.15rem;
	margin-bottom: 0.15rem;
}
.prose-chat :deep(li > p) {
	margin: 0;
}
</style>
