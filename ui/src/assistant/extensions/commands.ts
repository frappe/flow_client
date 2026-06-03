// `/` commands for the composer.
//
// Triggered only on an empty composer (Claude/Cursor style). `prefix` commands
// drop an atomic badge token like `/summarize` and let the user type arguments
// after it; `immediate` commands (clear, help) run on select via an
// `onImmediate` callback the host wires up with `.configure(...)`.

import { Node, mergeAttributes } from '@tiptap/core'
import { PluginKey } from '@tiptap/pm/state'
import { createSuggestionExtension } from 'frappe-ui'
import SuggestionList from '../components/SuggestionList.vue'
import { searchCommands, type CommandItem } from '../suggestions'
import { TOKEN_CLASS } from '../tokenClass'

// Atomic inline node holding the command name, rendered as a gray badge `/name`.
export const CommandNode = Node.create({
	name: 'command',
	group: 'inline',
	inline: true,
	atom: true,
	selectable: true,

	addAttributes() {
		return { name: { default: null } }
	},

	parseHTML() {
		return [{ tag: 'span[data-command]' }]
	},

	renderHTML({ node, HTMLAttributes }) {
		return [
			'span',
			mergeAttributes(HTMLAttributes, { 'data-command': '', class: TOKEN_CLASS }),
			`/${node.attrs.name ?? ''}`,
		]
	},

	renderText({ node }) {
		return `/${node.attrs.name ?? ''}`
	},
})

export const CommandSuggestion = createSuggestionExtension<CommandItem>({
	name: 'commandSuggestion',
	char: '/',
	pluginKey: new PluginKey('assistantCommand'),
	component: SuggestionList,
	allowSpaces: false,
	startOfLine: true,
	// Host calls `.configure({ onImmediate })` to receive immediate commands.
	addOptions: () => ({ onImmediate: undefined as ((name: string) => void) | undefined }),

	// Gate to an empty composer: the doc must hold nothing but the slash + query,
	// otherwise return no items (which hides the popup) so `/` mid-message is inert.
	items: ({ query, editor }) => {
		if (editor.state.doc.textContent !== `/${query}`) return []
		return searchCommands(query)
	},

	command: ({ editor, range, props: item }) => {
		if (item.mode === 'immediate') {
			editor.chain().focus().deleteRange(range).run()
			const ext = editor.extensionManager.extensions.find((e) => e.name === 'commandSuggestion')
			ext?.options.onImmediate?.(item.name)
			return
		}
		// Prefix: a badge token, then a plain space to type args after.
		editor
			.chain()
			.focus()
			.deleteRange(range)
			.insertContent([
				{ type: 'command', attrs: { name: item.name } },
				{ type: 'text', text: ' ' },
			])
			.run()
	},
})
