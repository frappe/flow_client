// Mocked chat engine — no backend.
//
// `send()` appends the user's message and then "streams" a scripted assistant
// reply: reasoning -> tool call -> streamed text -> an inline widget. This is
// the seam a real agent backend would later replace. Everything below the
// `scriptReply` function is generic plumbing.

import { provide, reactive, ref, type InjectionKey } from 'vue'
import type {
	ComposerSubmit,
	ConfirmationPart,
	Message,
	MessagePart,
	ReasoningPart,
	ToolPart,
} from './types'

let idCounter = 0
const uid = (prefix: string) => `${prefix}-${++idCounter}`

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

// Injected by Confirmation.vue to report the user's decision without prop-drilling.
// A stable *string* key (not Symbol) so provide/inject stay matched across HMR
// reloads of this module — a Symbol gets a new identity on every hot update,
// breaking the injection against an already-mounted provider.
export const RESPOND_CONFIRMATION = 'assistant:respond-confirmation' as unknown as InjectionKey<
	(id: string, value: string) => void
>

export function useChat() {
	const messages = reactive<Message[]>([])
	const streaming = ref(false)

	// Resolvers for confirmation parts awaiting a user decision, keyed by part id.
	const pendingConfirmations = new Map<string, (value: string) => void>()

	function respond(id: string, value: string) {
		const resolve = pendingConfirmations.get(id)
		if (!resolve) return
		pendingConfirmations.delete(id)
		resolve(value)
	}
	provide(RESPOND_CONFIRMATION, respond)

	function reset() {
		pendingConfirmations.clear()
		messages.splice(0, messages.length)
	}

	// Accepts a plain string (welcome chips, regenerate) or the composer's
	// structured payload (text + `@` mentions + a `/` command).
	async function send(input: string | ComposerSubmit) {
		if (streaming.value) return
		const payload: ComposerSubmit = typeof input === 'string' ? { text: input, mentions: [] } : input
		const { text, mentions, command } = payload
		if (!text.trim() && !mentions.length && !command) return

		messages.push({
			id: uid('user'),
			role: 'user',
			parts: [{ type: 'text', text }],
			mentions: mentions.length ? mentions : undefined,
			command,
		})

		const assistant: Message = reactive({
			id: uid('assistant'),
			role: 'assistant',
			parts: [],
			streaming: true,
		})
		messages.push(assistant)
		streaming.value = true

		try {
			await scriptReply(assistant, payload)
		} finally {
			assistant.streaming = false
			streaming.value = false
		}
	}

	// --- mocked reply script -------------------------------------------------

	async function scriptReply(msg: Message, payload: ComposerSubmit) {
		const { text: prompt, mentions, command } = payload

		// Reflect any command / mentions back into the reasoning so the wiring is visible.
		const intent = command ? `run "${command}" on` : 'answer'
		const refs = mentions.length ? ` Using context: ${mentions.map((m) => m.label).join(', ')}.` : ''

		// 1. Reasoning (streamed, then collapses)
		const reasoning = pushPart<ReasoningPart>(msg, { type: 'reasoning', text: '', streaming: true })
		await streamInto(
			() => reasoning.text,
			(v) => (reasoning.text = v),
			`The user wants me to ${intent}: "${prompt}".${refs} I'll look up the relevant data, then summarize it and show a metric card.`,
		)
		reasoning.streaming = false

		await sleep(700)

		// 2a. A quick lookup step (no expandable output — renders as a plain row).
		const lookup = pushPart(msg, {
			type: 'tool',
			name: 'read_schema',
			kind: 'tool',
			label: 'Read the sales table schema',
			status: 'running',
			input: { table: 'sales' },
		}) as ToolPart
		await sleep(1600)
		lookup.status = 'success'
		lookup.output = 'columns: id, amount, created, customer_id'
		await sleep(500)

		// 2b. Tool call — pending -> running -> success
		const tool = pushPart(msg, {
			type: 'tool',
			name: 'run_query',
			kind: 'tool',
			label: 'Run query',
			status: 'pending',
			input: { table: 'sales', metric: 'revenue', period: 'last_30_days' },
		}) as ToolPart
		await sleep(900)
		tool.status = 'running'
		await sleep(2200)
		tool.status = 'success'
		tool.output = { revenue: 128400, orders: 942, delta: '+12.4%' }
		await sleep(500)

		// 2c. A side-effectful action that needs the user's approval first.
		const decision = await confirm(msg, {
			title: 'Allow assistant to write report.pdf?',
			target: '~/report.pdf',
			reason: 'This file will be created outside the workspace directory.',
			detail: '/Users/saqibansari/report.pdf',
			choices: [
				{ value: 'deny', label: 'Deny', variant: 'subtle', align: 'start' },
				{ value: 'always', label: 'Always allow', variant: 'outline', align: 'end' },
				{ value: 'once', label: 'Allow once', variant: 'solid', primary: true, align: 'end' },
			],
		})

		if (decision === 'deny') {
			const declined = pushPart(msg, { type: 'text', text: '' })
			await streamInto(
				() => declined.text,
				(v) => (declined.text = v),
				"No problem — I won't write the file. Here's the summary instead:\n\n" +
					'- Revenue is up **12.4%** over the last 30 days.\n' +
					'- Orders held steady at 942.',
			)
			return
		}

		// Approved → run the write step, then carry on.
		const write = pushPart(msg, {
			type: 'tool',
			name: 'write_file',
			kind: 'tool',
			label: 'Write report.pdf',
			status: 'running',
			input: { path: '~/report.pdf' },
		}) as ToolPart
		await sleep(1500)
		write.status = 'success'
		write.output = 'Wrote 24 KB to ~/report.pdf'
		await sleep(500)

		// 3. A "skill" invocation (rendered with a skill accent)
		const skill = pushPart(msg, {
			type: 'tool',
			name: 'chart-builder',
			kind: 'skill',
			label: 'chart-builder',
			status: 'running',
			input: { type: 'metric-card' },
		}) as ToolPart
		await sleep(1800)
		skill.status = 'success'
		skill.output = 'Rendered metric card'
		await sleep(600)

		// 4. Streamed answer text
		const answer = pushPart(msg, { type: 'text', text: '' })
		await streamInto(
			() => answer.text,
			(v) => (answer.text = v),
			`Here's what I found for **last 30 days**:\n\n` +
				`- Revenue is up and orders are steady.\n` +
				`- See the metric below for the headline number.\n\n` +
				'```sql\nSELECT SUM(amount) FROM sales\nWHERE created > NOW() - INTERVAL 30 DAY;\n```',
		)

		// 5. Inline custom Vue component
		pushPart(msg, {
			type: 'widget',
			component: 'MetricCard',
			props: { label: 'Revenue (30d)', value: '$128,400', delta: '+12.4%', trend: 'up' },
		})
	}

	function pushPart<T extends MessagePart>(msg: Message, part: T): T {
		const reactivePart = reactive(part) as T
		msg.parts.push(reactivePart)
		return reactivePart
	}

	// Push a confirmation card and block until the user decides. The resolver,
	// keyed by id, is fired by `respond` (injected into Confirmation.vue); it
	// stamps `decision` so the card collapses to its resolved row.
	function confirm(msg: Message, data: Omit<ConfirmationPart, 'type' | 'id' | 'decision'>) {
		const part = pushPart<ConfirmationPart>(msg, { type: 'confirmation', id: uid('confirm'), ...data })
		return new Promise<string>((resolve) => {
			pendingConfirmations.set(part.id, (value) => {
				part.decision = value
				resolve(value)
			})
		})
	}

	// Token-by-token stream simulation over a string.
	async function streamInto(get: () => string, set: (v: string) => void, full: string) {
		const tokens = full.match(/\S+\s*|\s+/g) ?? [full]
		for (const t of tokens) {
			set(get() + t)
			await sleep(55)
		}
	}

	return { messages, streaming, send, reset }
}
