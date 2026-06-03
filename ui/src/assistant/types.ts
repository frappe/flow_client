// Message model for the assistant chat.
//
// A message is an ordered list of *parts* rather than a single markdown blob.
// This mirrors the ai-elements / AI SDK data model and lets tools, reasoning,
// and inline Vue widgets all be first-class siblings of plain text.

export type Role = 'user' | 'assistant'

export type ToolStatus = 'pending' | 'running' | 'success' | 'error'

export interface TextPart {
	type: 'text'
	// Markdown source. Rendered by Markdown.vue.
	text: string
}

export interface ReasoningPart {
	type: 'reasoning'
	text: string
	// While true the block shows a live "thinking" state and stays expanded.
	streaming?: boolean
}

export interface ToolPart {
	type: 'tool'
	// e.g. "run_query", "search_docs". A skill invocation is just a tool
	// whose name is the skill (rendered with a different accent — see ToolPart.vue).
	name: string
	kind?: 'tool' | 'skill'
	status: ToolStatus
	input?: Record<string, unknown>
	output?: unknown
	// Optional human label, falls back to `name`.
	label?: string
}

// Renders a registered Vue component inline in the message stream.
// `component` is a key into the widget registry (see widgets/registry.ts),
// never a raw component — keeps the data layer serializable / backend-ready.
export interface WidgetPart {
	type: 'widget'
	component: string
	props?: Record<string, unknown>
}

// A button in a confirmation card. Data-driven so the same card serves a simple
// Confirm/Cancel and the Deny/Always/Once permission pattern.
export interface ConfirmationChoice {
	// Returned to the engine when picked (e.g. 'once' | 'always' | 'deny').
	value: string
	label: string
	// Maps onto frappe-ui Button props.
	variant?: 'solid' | 'subtle' | 'outline' | 'ghost'
	theme?: 'gray' | 'red'
	// The primary action — gets the ⌘↵ shortcut. Esc always picks `deny`-aligned.
	primary?: boolean
	// 'start' floats left (Deny), 'end' floats right (the allows). Default 'end'.
	align?: 'start' | 'end'
}

// A side-effectful action the assistant proposes and blocks on until the user
// answers. Renders as a prominent card; once `decision` is set it collapses to a
// compact resolved row.
export interface ConfirmationPart {
	type: 'confirmation'
	id: string
	title: string
	// Primary subject line, e.g. "~/report.pdf".
	target?: string
	// Why approval is needed / a warning, e.g. "outside the workspace directory".
	reason?: string
	// Monospace detail block (full path, command, payload).
	detail?: string
	choices: ConfirmationChoice[]
	// Set to the chosen `value` once resolved.
	decision?: string
}

export type MessagePart = TextPart | ReasoningPart | ToolPart | WidgetPart | ConfirmationPart

// A resolved `@` reference attached to a user turn. `type` is the provider group
// (e.g. "Document", "Person") — the assistant core stays domain-agnostic.
export interface MentionRef {
	id: string
	type: string
	label: string
}

// What the composer emits on submit: the plain text plus any structured `@`
// references and a leading `/` command. This is the shape `useChat.send` consumes.
export interface ComposerSubmit {
	text: string
	mentions: MentionRef[]
	command?: string
}

export interface Message {
	id: string
	role: Role
	parts: MessagePart[]
	// Structured `@` references the user attached to this turn.
	mentions?: MentionRef[]
	// A leading `/` command the user invoked (e.g. "summarize").
	command?: string
	// True while the assistant is still streaming this message.
	streaming?: boolean
}
