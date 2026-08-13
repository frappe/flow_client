import { createApp, watch } from "vue";
import App from "@/App.vue";
import { useStore } from "@/store";
import { readPanelState, writePanelState } from "@/lib/panelState";
import "@/index.css";

const PANEL_WIDTH = 420;
const MIN_WIDTH = 360;

// Slide-in overlay panel injected into the Frappe desk. The Vue app (with real
// frappe-ui components) mounts inside #flow-root; all bundle CSS is scoped to
// that id so nothing leaks onto the desk.
class FlowPanel {
	constructor() {
		const saved = readPanelState();
		this.visible = Boolean(saved.open);
		this._halfWidth = saved.width || PANEL_WIDTH;
		// Fullscreen is the default mode; a saved preference wins on reload.
		this._initialFullscreen = saved.fullscreen ?? true;

		this._mount();
		this._syncTheme();
		this._syncVisualViewport();
		this._registerShortcut();
		this._addMobileTrigger();

		watch(this.store.sessionName, () => this._persist());
	}

	get fullscreen() {
		return this.store.fullscreen.value;
	}

	_mount() {
		this.store = useStore();
		this.store.fullscreen.value = this._initialFullscreen;

		this.root = document.createElement("div");
		this.root.id = "flow-root";
		Object.assign(this.root.style, {
			position: "fixed",
			top: "0",
			right: "0",
			width: this.fullscreen ? "100vw" : `${this._halfWidth}px`,
			height: "100vh",
			zIndex: "1040",
			// A restored-open panel renders in place (no slide) so a refresh is seamless.
			transform: this.visible ? "translateX(0)" : "translateX(100%)",
			transition: "transform 0.22s ease",
			boxShadow: "-2px 0 16px rgba(0, 0, 0, 0.08)",
		});
		document.body.appendChild(this.root);

		this.app = createApp(App, {
			onClose: () => this.hide(),
			onToggleFullscreen: () => this.toggleFullscreen(),
		});
		this.app.mount(this.root);

		this._addResizeHandle();
	}

	// Thin grab strip on the panel's left edge. Dragging it changes the panel
	// width (anchored to the right). Appended after mount so Vue's render
	// doesn't clobber it.
	_addResizeHandle() {
		const handle = document.createElement("div");
		Object.assign(handle.style, {
			position: "absolute",
			top: "0",
			left: "0",
			width: "6px",
			height: "100%",
			cursor: "ew-resize",
			zIndex: "10",
		});
		this.root.appendChild(handle);

		const onMove = (e) => {
			const max = window.innerWidth - 80;
			const width = Math.min(max, Math.max(MIN_WIDTH, window.innerWidth - e.clientX));
			this.root.style.width = `${width}px`;
			this._halfWidth = width;
			// A manual resize takes the panel out of fullscreen; keep the header icon honest.
			this.store.fullscreen.value = false;
		};
		const onUp = () => {
			document.removeEventListener("mousemove", onMove);
			document.removeEventListener("mouseup", onUp);
			document.body.style.userSelect = "";
			this.root.style.transition = this._savedTransition;
			this._persist();
		};
		handle.addEventListener("mousedown", (e) => {
			e.preventDefault();
			// Drop the width transition while dragging so it tracks the cursor.
			this._savedTransition = this.root.style.transition;
			this.root.style.transition = "none";
			document.body.style.userSelect = "none";
			document.addEventListener("mousemove", onMove);
			document.addEventListener("mouseup", onUp);
		});
	}

	// Mirror the desk's light/dark theme onto the panel root so scoped tokens
	// resolve to the right palette.
	_syncTheme() {
		const apply = () => {
			const theme = document.documentElement.getAttribute("data-theme") || "light";
			this.root.setAttribute("data-theme", theme);
		};
		apply();
		new MutationObserver(apply).observe(document.documentElement, {
			attributes: true,
			attributeFilter: ["data-theme"],
		});
	}

	_syncVisualViewport() {
		const viewport = window.visualViewport;
		const sync = () => {
			this.root.style.top = `${viewport?.offsetTop || 0}px`;
			this.root.style.height = `${viewport?.height || window.innerHeight}px`;
		};
		viewport?.addEventListener("resize", sync);
		viewport?.addEventListener("scroll", sync);
		window.addEventListener("orientationchange", sync);
		sync();
	}

	_registerShortcut() {
		frappe.ui.keys.add_shortcut({
			shortcut: "ctrl+i",
			action: () => this.toggle(),
			description: __("Toggle Flow panel"),
			ignore_inputs: true,
		});
	}

	_addMobileTrigger() {
		this.mobileTrigger = document.createElement("button");
		this.mobileTrigger.type = "button";
		this.mobileTrigger.setAttribute("aria-label", __("Open Flow assistant"));
		this.mobileTrigger.title = __("Open Flow assistant");
		this.mobileTrigger.textContent = "Flow";
		Object.assign(this.mobileTrigger.style, {
			position: "fixed",
			right: "16px",
			bottom: "calc(16px + env(safe-area-inset-bottom, 0px))",
			width: "52px",
			height: "52px",
			zIndex: "1039",
			border: "0",
			borderRadius: "50%",
			background: "var(--primary, #171717)",
			color: "var(--fg-color, #fff)",
			boxShadow: "0 6px 20px rgba(0, 0, 0, 0.22)",
			fontSize: "13px",
			fontWeight: "600",
			cursor: "pointer",
		});
		this.mobileTrigger.addEventListener("click", () => this.show());
		document.body.appendChild(this.mobileTrigger);

		const sync = () => {
			const mobile =
				window.matchMedia("(any-pointer: coarse)").matches || window.innerWidth <= 768;
			this.mobileTrigger.style.display = mobile && !this.visible ? "block" : "none";
		};
		this._syncMobileTrigger = sync;
		window.addEventListener("resize", sync);
		sync();
	}

	show() {
		this.visible = true;
		this.root.style.transform = "translateX(0)";
		this._syncMobileTrigger?.();
		this.store.restoreSession();
		this._persist();
	}

	hide() {
		this.visible = false;
		this.root.style.transform = "translateX(100%)";
		this._syncMobileTrigger?.();
		this._persist();
	}

	toggle() {
		this.visible ? this.hide() : this.show();
	}

	// Expand to the full viewport width, or restore the half-screen width. State
	// lives in the store so the header icon tracks it reactively.
	toggleFullscreen() {
		const next = !this.fullscreen;
		this.store.fullscreen.value = next;
		this.root.style.width = next ? "100vw" : `${this._halfWidth}px`;
		this._persist();
	}

	_persist() {
		writePanelState({
			open: this.visible,
			fullscreen: this.fullscreen,
			width: this._halfWidth,
			session: this.store.sessionName.value,
		});
	}
}

frappe.provide("frappe.flow");
$(document).on("app_ready", () => {
	frappe.flow.panel = new FlowPanel();
});
