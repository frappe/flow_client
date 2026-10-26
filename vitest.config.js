import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// The panel's test runner. Deliberately NOT `vite.config.js`: that file is a library build (a single
// IIFE emitted into the app's public dir, `process.env.NODE_ENV` pinned to "production", the desk's
// CSS prefixing) and none of it applies to mounting one component in a DOM. What IS shared is the
// part a test must not get wrong — the same `@vitejs/plugin-vue` that compiles the SFC in the real
// build, and the same two `resolve.alias` entries, so a test imports the very module the bundle does.
export default defineConfig({
	plugins: [vue()],
	resolve: {
		alias: [
			{ find: "@", replacement: fileURLToPath(new URL("./frontend/src", import.meta.url)) },
			{
				find: "frappe-ui/src",
				replacement: fileURLToPath(
					new URL("./node_modules/frappe-ui/src", import.meta.url)
				),
			},
		],
	},
	test: {
		// A real DOM. Every assertion in `frontend/tests/` is about what a person sees, so it reads
		// the rendered tree — `innerHTML`, `textContent`, computed styles — and never the source text
		// of the component. `flow/tests/test_s21_confirm_card_source.py` says in its own docstring
		// that it proves "no pixel, no layout and no behaviour"; this is what replaces it.
		environment: "jsdom",
		setupFiles: ["./frontend/tests/setup.js"],
		// The component's OWN `<style scoped>`, compiled by the same plugin as the real build and
		// inserted into the document, so `getComputedStyle` answers about the real stylesheet rather
		// than about nothing. What this does NOT bring in is Tailwind's generated utilities — they are
		// built into the global bundle, not into the SFC — which is why the height-cap test also walks
		// the rendered ancestor chain for clamping classes. See its comment.
		css: true,
		include: ["frontend/tests/**/*.spec.js"],
		// No `globals: true`: every test imports `describe`/`it`/`expect` explicitly, so the files
		// stay readable to eslint's `eslint:recommended` without a new env.
		globals: false,
	},
});
