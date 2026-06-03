// @flow/ui — public API.
//
// Build-less source package: consumers import from `@flow/ui` (this barrel) or
// deep-import any file via `@flow/ui/<path>` (see the `./*` export map). The
// host app's bundler compiles the raw .vue/.ts; vue / vue-router / frappe-ui
// and the other UI libs are peer dependencies provided by the host.

// AI assistant components.
export { default as Assistant } from './assistant/Assistant.vue'
export { useChat, RESPOND_CONFIRMATION } from './assistant/useChat'
export { widgetRegistry } from './assistant/widgets/registry'
export * from './assistant/types'

// Generic UI primitives — prototyped here, destined for frappe-ui. Kept in a
// separate `base/` folder so the eventual lift into frappe-ui is a clean move.
export * from './base'
