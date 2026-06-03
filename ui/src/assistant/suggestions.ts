// Generic registries for the composer's `@` mentions and `/` commands.
//
// Nothing here is domain-specific: mentions come from mock "providers" and
// commands are plain intents. A real app swaps the mock arrays / search
// functions for backend calls (or per-type providers) without touching the
// editor extensions or the popup — this module is the single config seam.

import {
	Eraser,
	FileText,
	HelpCircle,
	Languages,
	MessageSquare,
	PencilLine,
	TextQuote,
	User,
	type LucideIcon,
} from 'lucide-vue-next'

// An `@`-mentionable resource. `type` doubles as the popup's group header.
export interface MentionItem {
	id: string
	type: string
	label: string
	sublabel?: string
	icon?: LucideIcon
}

// A `/` command. `prefix` commands drop a token into the composer and let the
// user type arguments after it; `immediate` commands run the moment they're picked.
export interface CommandItem {
	name: string
	label: string
	description?: string
	icon?: LucideIcon
	mode: 'prefix' | 'immediate'
}

// --- mock data (generic placeholders) -------------------------------------

const mentions: MentionItem[] = [
	{ id: 'doc-1', type: 'Document', label: 'Project Brief', sublabel: 'Updated 2d ago', icon: FileText },
	{ id: 'doc-2', type: 'Document', label: 'Q2 Planning Notes', sublabel: 'Updated 1w ago', icon: FileText },
	{ id: 'person-1', type: 'Person', label: 'Alex Rivera', sublabel: 'alex@example.com', icon: User },
	{ id: 'person-2', type: 'Person', label: 'Sam Chen', sublabel: 'sam@example.com', icon: User },
	{ id: 'thread-1', type: 'Thread', label: 'Earlier in this chat', icon: MessageSquare },
]

const commands: CommandItem[] = [
	{ name: 'summarize', label: 'Summarize', description: 'Condense the referenced content', icon: TextQuote, mode: 'prefix' },
	{ name: 'explain', label: 'Explain', description: 'Break it down step by step', icon: HelpCircle, mode: 'prefix' },
	{ name: 'rewrite', label: 'Rewrite', description: 'Rephrase the text', icon: PencilLine, mode: 'prefix' },
	{ name: 'translate', label: 'Translate', description: 'Translate to another language', icon: Languages, mode: 'prefix' },
	{ name: 'clear', label: 'Clear chat', description: 'Start a new conversation', icon: Eraser, mode: 'immediate' },
	{ name: 'help', label: 'Help', description: 'See what I can do', icon: HelpCircle, mode: 'immediate' },
]

// --- search (prefix match; the swap-in seam for a backend) -----------------

const startsWith = (s: string, q: string) => s.toLowerCase().startsWith(q.toLowerCase())

export function searchMentions(query: string): MentionItem[] {
	const q = query.trim()
	return mentions.filter((m) => !q || startsWith(m.label, q)).slice(0, 10)
}

export function searchCommands(query: string): CommandItem[] {
	const q = query.trim()
	return commands.filter((c) => !q || startsWith(c.name, q) || startsWith(c.label, q))
}
