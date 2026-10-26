// jsdom implements no layout, so `Element.prototype.scrollIntoView` does not exist. Without this the
// card's `onMounted` hook raises inside a `nextTick`, which vitest reports as an unhandled rejection
// and warns "might cause false positive tests" — a warning, not a failure, i.e. exactly the shape of
// thing that rots into ignored noise.
//
// It is installed as a RECORDER rather than a no-op, because what it records is a fact worth
// asserting: run 12 could only check that the source text of the component contained
// `scrollIntoView({ block: "start"`. Here the call itself is observed, with its arguments.
import { beforeEach } from "vitest";

export const scrollCalls = [];

Element.prototype.scrollIntoView = function (options) {
	scrollCalls.push({ el: this, options });
};

beforeEach(() => {
	scrollCalls.length = 0;
});
