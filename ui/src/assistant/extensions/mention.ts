// `@` mentions for the composer.
//
// Two pieces: an atomic inline node that holds a structured ref and renders like
// inline code, and a suggestion (built on frappe-ui's factory) that lists
// matches and inserts the node. Keeping the node atomic means a mention is a
// single, deletable token rather than editable text.

import { Node, mergeAttributes } from '@tiptap/core'
import { PluginKey } from '@tiptap/pm/state'
import { createSuggestionExtension } from 'frappe-ui'
import SuggestionList from '../components/SuggestionList.vue'
import { searchMentions, type MentionItem } from '../suggestions'
import { TOKEN_CLASS } from '../tokenClass'

export const MentionNode = Node.create({
	name: 'mention',
	group: 'inline',
	inline: true,
	atom: true,
	selectable: true,

	addAttributes() {
		return {
			id: { default: null },
			// Provider group (Document/Person/…). Named `mtype` to avoid colliding
			// with tiptap's own node `type`.
			mtype: { default: null },
			label: { default: null },
		}
	},

	parseHTML() {
		return [{ tag: 'span[data-mention]' }]
	},

	renderHTML({ node, HTMLAttributes }) {
		return [
			'span',
			mergeAttributes(HTMLAttributes, {
				'data-mention': '',
				'data-id': node.attrs.id,
				'data-mtype': node.attrs.mtype,
				class: TOKEN_CLASS,
			}),
			`@${node.attrs.label ?? ''}`,
		]
	},

	renderText({ node }) {
		return `@${node.attrs.label ?? ''}`
	},
})

export const MentionSuggestion = createSuggestionExtension<MentionItem>({
	name: 'mentionSuggestion',
	char: '@',
	pluginKey: new PluginKey('assistantMention'),
	component: SuggestionList,
	allowSpaces: false,
	items: ({ query }) => searchMentions(query),
	command: ({ editor, range, props: item }) => {
		editor
			.chain()
			.focus()
			.insertContentAt(range, [
				{ type: 'mention', attrs: { id: item.id, mtype: item.type, label: item.label } },
				{ type: 'text', text: ' ' },
			])
			.run()
	},
})
