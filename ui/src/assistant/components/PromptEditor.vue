<template>
	<EditorContent :editor="editor" data-slot="control" />
</template>

<script setup lang="ts">
import { Placeholder } from '@tiptap/extensions'
import type { Editor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { watch } from 'vue'
import type { ComposerSubmit, MentionRef } from '../types'
import { CommandNode, CommandSuggestion } from '../extensions/commands'
import { MentionNode, MentionSuggestion } from '../extensions/mention'
// Reuse frappe-ui's TextEditor styling (.ProseMirror base, placeholder, lists)
// rather than re-implementing it — stay on the standard.
import 'frappe-ui/editor-style.css'

const props = withDefaults(
	defineProps<{
		/** Placeholder shown when the editor is empty. */
		placeholder?: string
		/** Disables editing and submission. */
		disabled?: boolean
		/** Focuses the editor on mount. */
		autofocus?: boolean
	}>(),
	{ placeholder: '', disabled: false, autofocus: false },
)

const emit = defineEmits<{
	/** Fired on submit (Enter outside a list, or Cmd/Ctrl+Enter). */
	submit: [value: ComposerSubmit]
	/** Fired when an `immediate` slash command (e.g. clear) is invoked. */
	command: [name: string]
}>()

/** Plain-text mirror of the editor, so callers can gate the send button and
 *  clear after sending. The full structured payload is delivered via `submit`. */
const model = defineModel<string>({ default: '' })

const editor = useEditor({
	content: model.value,
	editable: !props.disabled,
	autofocus: props.autofocus,
	extensions: [
		// Headings off — chat composers don't take headings (matches Claude).
		StarterKit.configure({ heading: false }),
		Placeholder.configure({ placeholder: () => props.placeholder }),
		MentionNode,
		MentionSuggestion,
		CommandNode,
		CommandSuggestion.configure({ onImmediate: (name: string) => emit('command', name) }),
	],
	editorProps: {
		attributes: {
			'aria-label': 'Message',
			// Same prose classes frappe-ui's TextEditor applies, full width.
			class: 'prose prose-sm max-w-none max-h-[200px] overflow-y-auto focus:outline-none',
		},
		handleKeyDown: (_view, event) => {
			if (event.key !== 'Enter') return false
			const e = editor.value
			if (!e) return false

			// Cmd/Ctrl+Enter always submits, even mid-list.
			if (event.metaKey || event.ctrlKey) {
				event.preventDefault()
				submit()
				return true
			}
			// Shift+Enter → hard break (StarterKit default).
			if (event.shiftKey) return false
			// Inside structural blocks, let Enter do its job (new item / newline).
			if (e.isActive('listItem') || e.isActive('codeBlock') || e.isActive('blockquote')) {
				return false
			}
			// Otherwise Enter sends.
			event.preventDefault()
			submit()
			return true
		},
	},
	onUpdate: () => {
		model.value = editor.value?.getText() ?? ''
	},
})

/** Walk the doc into a structured payload: collect `@` mention nodes and detect
 *  a leading inline-code `/command` token. */
function buildSubmit(e: Editor): ComposerSubmit {
	const mentions: MentionRef[] = []
	let command: string | undefined
	e.state.doc.descendants((node) => {
		if (node.type.name === 'mention') {
			mentions.push({ id: node.attrs.id, type: node.attrs.mtype, label: node.attrs.label })
		} else if (node.type.name === 'command') {
			command = node.attrs.name
		}
	})

	let text = e.getText().trim()
	// Drop the leading command token from the message text — it lives in `command`.
	if (command) text = text.replace(/^\/\S+\s*/, '')

	return { text, mentions, command }
}

function submit() {
	const e = editor.value
	if (!e || props.disabled) return
	const payload = buildSubmit(e)
	if (!payload.text && !payload.mentions.length && !payload.command) return
	emit('submit', payload)
}

// External clears (caller sets v-model to '') reset the editor.
watch(model, (val) => {
	const e = editor.value
	if (e && val === '' && e.getText() !== '') e.commands.clearContent()
})

watch(
	() => props.disabled,
	(d) => editor.value?.setEditable(!d),
)

// Let the parent's send button trigger a submit (the payload lives in the editor).
defineExpose({ submit })
</script>
