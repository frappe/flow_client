// The payload that carries a person's DECISION back to the engine.
//
// Three lines, in a module of their own, and the reason is that they could not be tested where they
// were. They lived inside `store.js`'s `answerQuestion`, and `store.js` cannot be imported by a test
// — so the only thing a test could do was read the source text and grep for the safe spelling. A
// reviewer showed exactly what that is worth: they left the safe line in place, added a second plain
// object beside it, sent THAT one, and the whole suite stayed green while the defect was fully
// restored. A test that cannot go red is a comment.
//
// THE DEFECT ITSELF. `q.key` is a tool-call id that arrives from the model's own reply — set
// verbatim from the provider payload, and on the resume path spread out of a stored JSON blob
// without a field of it being validated. On a plain object, `answers["__proto__"] = "Approve"`
// invokes the prototype setter, which ignores a string: no own property is created, `JSON.stringify`
// sends `{}`, and an approval a person clicked is transmitted as though they never answered it.
//
// It is the same inherited-key defect the display side had (`lib/toolMeta.js`'s Maps), on the
// surface that carries the decision rather than the picture of it — and worse here, because the card
// failed loudly and this fails silently, in the direction of doing nothing.
//
// A null-prototype object has no setter to invoke, and `JSON.stringify` treats it identically
// otherwise, so nothing about the wire format changes.

/**
 * Collect every answered question into the object that is sent to the engine.
 *
 * @param {Array<{key: string, _answer: string|undefined}>} questions
 * @returns {Object} keyed by the question's tool-call id, with no prototype.
 */
export function answersPayload(questions) {
	const answers = Object.create(null);
	for (const q of questions) answers[q.key] = q._answer;
	return answers;
}
