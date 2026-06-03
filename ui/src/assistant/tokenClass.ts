// Shared Tailwind classes for the `@` mention and `/` command tokens, so the
// composer (editor node rendering) and the transcript stay in sync. Tailwind
// utilities only — no custom CSS class.
export const TOKEN_CLASS =
	'inline-block box-decoration-clone rounded-sm px-1 py-0.5 cursor-pointer font-semibold bg-surface-white text-ink-gray-8 hover:bg-surface-gray-1'
