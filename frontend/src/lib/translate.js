// Thin wrapper over the desk's global translator so components can stay
// translatable without depending on it being present (e.g. in isolation).
export function __(message, args) {
	if (typeof window !== "undefined" && typeof window.__ === "function") {
		return window.__(message, args);
	}
	return substitute(message, args);
}

// The fallback used to return the message unsubstituted, so away from the desk every positional
// string rendered its own placeholder: the approval card's headline read `Run "{0}" on {1}` and named
// neither the action nor the doctype. That is not cosmetic on this surface — a headline that names no
// action is a headline a person cannot check the arguments against — and it also hid the headline's
// values from every test, because a test in a bare DOM was measuring the placeholder and not the
// value. Substituting here is the desk's own rule (`{0}`, by position), so the two agree.
function substitute(message, args) {
	const text = String(message ?? "");
	if (!args) return text;
	return text.replace(/\{(\d+)\}/g, (whole, i) =>
		args[i] !== undefined ? String(args[i]) : whole
	);
}
