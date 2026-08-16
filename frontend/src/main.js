import { createApp, watch } from "vue";
import App from "@/App.vue";
import { useStore } from "@/store";
import { readPanelState, writePanelState } from "@/lib/panelState";
import { getPageContextIdentity } from "@/lib/pageContext";
import "@/index.css";

const PANEL_WIDTH = 420;
const MIN_WIDTH = 360;
const MINIMIZED_WIDTH = 400;
const MINIMIZED_HEIGHT = 44;
const ASK_BUTTON_CLASS = "flow-ask-button";

function createAiMark(size = 18) {
	const mark = document.createElement("span");
	mark.setAttribute("aria-hidden", "true");
	Object.assign(mark.style, {
		display: "inline-flex",
		alignItems: "center",
		justifyContent: "center",
		width: `${size}px`,
		height: `${size}px`,
		flex: `0 0 ${size}px`,
		borderRadius: "5px",
		background: "var(--gray-700, #374151)",
		color: "white",
	});
	mark.innerHTML = `
		<svg width="${size * 0.62}" height="${size * 0.62}" viewBox="0 0 24 24" fill="currentColor">
			<path d="M12 2.5l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.9L12 2.5z"></path>
			<path d="M18.5 14l.95 2.55L22 17.5l-2.55.95L18.5 21l-.95-2.55L15 17.5l2.55-.95L18.5 14z"></path>
		</svg>`;
	return mark;
}

function createIconButton(icon, label, action) {
	const button = document.createElement("button");
	button.type = "button";
	button.className = "btn btn-link btn-sm";
	button.title = label;
	button.setAttribute("aria-label", label);
	button.innerHTML = frappe.utils.icon(icon, "sm");
	Object.assign(button.style, {
		display: "inline-flex",
		alignItems: "center",
		justifyContent: "center",
		width: "32px",
		height: "32px",
		padding: "0",
		color: "var(--text-muted, #6b7280)",
	});
	button.addEventListener("click", action);
	return button;
}

// Slide-in overlay injected into the Frappe Desk. The minimized state is a
// lightweight bottom bar styled after Frappe's minimized email dialogs without
// entering the global Dialog/backdrop stack, so it can safely coexist with them.
class FlowPanel {
	constructor() {
		const saved = readPanelState();
		this.minimized = Boolean(saved.open && saved.minimized);
		this.visible = Boolean(saved.open && !this.minimized);
		this._halfWidth = this._clampPanelWidth(saved.width || PANEL_WIDTH);
		this._initialFullscreen = saved.fullscreen ?? true;
		this._lastTrigger = null;
		this._barObserver = null;
		this._barPositionFrame = null;

		this._mount();
		this._mountMinimizedBar();
		this._syncTheme();
		this._registerShortcut();
		this._registerPageTrigger();

		watch(this.store.sessionName, () => this._persist());
		if (this.minimized) {
			requestAnimationFrame(() => {
				if (this.minimized) this._showMinimizedBar({ focus: false });
			});
		}
	}

	get fullscreen() {
		return this.store.fullscreen.value;
	}

	get open() {
		return this.visible || this.minimized;
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
			transform: this.visible ? "translateX(0)" : "translateX(100%)",
			transition: "transform 0.22s ease",
			boxShadow: "-2px 0 16px rgba(0, 0, 0, 0.08)",
		});
		this.root.inert = !this.visible;
		this.root.setAttribute("aria-hidden", String(!this.visible));
		document.body.appendChild(this.root);

		this.app = createApp(App, {
			onClose: () => this.hide(),
			onMinimize: () => this.minimize(),
			onToggleFullscreen: () => this.toggleFullscreen(),
		});
		this.app.mount(this.root);

		this._addResizeHandle();
	}

	_mountMinimizedBar() {
		this.minimizedBar = document.createElement("div");
		this.minimizedBar.id = "flow-minimized-bar";
		this.minimizedBar.setAttribute("role", "region");
		this.minimizedBar.setAttribute("aria-label", __("Ask Flow"));
		this.minimizedBar.setAttribute("aria-hidden", "true");
		this.minimizedBar.inert = true;
		Object.assign(this.minimizedBar.style, {
			position: "fixed",
			right: "15px",
			bottom: "0",
			width: `${MINIMIZED_WIDTH}px`,
			height: `${MINIMIZED_HEIGHT}px`,
			display: "none",
			alignItems: "center",
			zIndex: "1060",
			background: "var(--card-bg, var(--fg-color, #fff))",
			color: "var(--text-color, #1f272e)",
			border: "1px solid var(--border-color, #d1d8dd)",
			borderBottom: "0",
			borderRadius: "var(--border-radius-md, 8px) var(--border-radius-md, 8px) 0 0",
			boxShadow: "var(--shadow-lg, 0 10px 30px rgba(0, 0, 0, 0.18))",
			overflow: "hidden",
		});

		this.minimizedTitle = document.createElement("button");
		this.minimizedTitle.type = "button";
		this.minimizedTitle.setAttribute("aria-label", __("Restore Flow"));
		Object.assign(this.minimizedTitle.style, {
			display: "flex",
			alignItems: "center",
			gap: "8px",
			minWidth: "0",
			flex: "1",
			height: "100%",
			padding: "0 12px",
			border: "0",
			background: "transparent",
			color: "inherit",
			fontWeight: "600",
			textAlign: "left",
			cursor: "pointer",
		});
		this.minimizedTitle.appendChild(createAiMark(18));
		const label = document.createElement("span");
		label.textContent = __("Ask Flow");
		Object.assign(label.style, {
			overflow: "hidden",
			textOverflow: "ellipsis",
			whiteSpace: "nowrap",
		});
		this.minimizedTitle.appendChild(label);
		this.minimizedTitle.addEventListener("click", () => this.show());
		this.minimizedBar.appendChild(this.minimizedTitle);

		const actions = document.createElement("div");
		Object.assign(actions.style, {
			display: "flex",
			alignItems: "center",
			paddingInlineEnd: "6px",
		});
		actions.appendChild(createIconButton("expand", __("Restore Flow"), () => this.show()));
		actions.appendChild(createIconButton("close", __("Close Flow"), () => this.hide()));
		this.minimizedBar.appendChild(actions);
		document.body.appendChild(this.minimizedBar);

		this._onViewportResize = () => {
			this._resizePanelForViewport();
			this._scheduleMinimizedBarPosition();
		};
		window.addEventListener("resize", this._onViewportResize);
	}

	// Thin grab strip on the panel's left edge. Dragging it changes the panel
	// width (anchored to the right). Appended after mount so Vue doesn't clobber it.
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
			const width = this._clampPanelWidth(window.innerWidth - e.clientX, 80);
			this.root.style.width = `${width}px`;
			this._halfWidth = width;
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
			this._savedTransition = this.root.style.transition;
			this.root.style.transition = "none";
			document.body.style.userSelect = "none";
			document.addEventListener("mousemove", onMove);
			document.addEventListener("mouseup", onUp);
		});
	}

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

	_registerShortcut() {
		frappe.ui.keys.add_shortcut({
			shortcut: "ctrl+i",
			action: () => this.toggle(),
			description: __("Toggle Flow panel"),
			ignore_inputs: true,
		});
	}

	_registerPageTrigger() {
		this._onPageChange = () =>
			requestAnimationFrame(() => {
				this._installAskFlowButton();
				if (this.open) this._suggestCurrentPageContext();
			});
		$(document).on("page-change.flow-panel", this._onPageChange);
		this._installAskFlowButton();
	}

	_installAskFlowButton() {
		const activePage = window.cur_page?.page;
		const titleArea =
			activePage?.page?.$title_area?.get?.(0) ||
			activePage?.querySelector?.(".page-head .page-title > .title-area");
		const pageTitle = titleArea?.parentElement;
		if (!titleArea || !pageTitle || pageTitle.querySelector(`.${ASK_BUTTON_CLASS}`)) return;

		const button = document.createElement("button");
		button.type = "button";
		button.className = `btn btn-default btn-sm ${ASK_BUTTON_CLASS}`;
		button.title = __("Ask Flow");
		button.setAttribute("aria-label", __("Ask Flow"));
		button.setAttribute("aria-controls", "flow-root");
		Object.assign(button.style, {
			display: "inline-flex",
			alignItems: "center",
			gap: "6px",
			marginInlineStart: "8px",
			flexShrink: "0",
		});
		button.appendChild(createAiMark(18));
		const label = document.createElement("span");
		label.className = "hidden-xs";
		label.textContent = __("Ask Flow");
		button.appendChild(label);
		button.addEventListener("click", () => this.show(button, { forceContext: true }));
		titleArea.insertAdjacentElement("afterend", button);
		this._syncAskButtons();
	}

	_showPanel() {
		this.visible = true;
		this.minimized = false;
		this._hideMinimizedBar();
		this.root.inert = false;
		this.root.style.transform = "translateX(0)";
		this.root.setAttribute("aria-hidden", "false");
		this.store.restoreSession();
		this.store.focusTick.value++;
		this._syncAskButtons();
		this._persist();
	}

	_hidePanelRoot() {
		this.visible = false;
		this.root.inert = true;
		this.root.style.transform = "translateX(100%)";
		this.root.setAttribute("aria-hidden", "true");
	}

	_showMinimizedBar({ focus = true } = {}) {
		if (!this.minimized) return;
		this.minimizedBar.inert = false;
		this.minimizedBar.style.display = "flex";
		this.minimizedBar.setAttribute("aria-hidden", "false");
		this._startMinimizedBarObserver();
		this._positionMinimizedBar();
		if (focus) {
			requestAnimationFrame(() => {
				if (this.minimized) this.minimizedTitle.focus();
			});
		}
	}

	_hideMinimizedBar() {
		this.minimizedBar.inert = true;
		this.minimizedBar.style.display = "none";
		this.minimizedBar.setAttribute("aria-hidden", "true");
		this._stopMinimizedBarObserver();
	}

	_startMinimizedBarObserver() {
		if (this._barObserver) return;
		this._barObserver = new MutationObserver(() => this._scheduleMinimizedBarPosition());
		this._barObserver.observe(document.body, {
			subtree: true,
			childList: true,
			attributes: true,
			attributeFilter: ["class"],
		});
	}

	_stopMinimizedBarObserver() {
		this._barObserver?.disconnect();
		this._barObserver = null;
		if (this._barPositionFrame) cancelAnimationFrame(this._barPositionFrame);
		this._barPositionFrame = null;
	}

	_scheduleMinimizedBarPosition() {
		if (!this.minimized || this._barPositionFrame) return;
		this._barPositionFrame = requestAnimationFrame(() => {
			this._barPositionFrame = null;
			if (this.minimized) this._positionMinimizedBar();
		});
	}

	_positionMinimizedBar() {
		const nativeMinimizedDialogs = document.querySelectorAll(
			"body > .modal.show.modal-minimize"
		).length;
		const mobile = window.matchMedia("(max-width: 575px)").matches;
		this.minimizedBar.style.bottom = `${nativeMinimizedDialogs * MINIMIZED_HEIGHT}px`;
		this.minimizedBar.style.right = mobile ? "0" : "15px";
		this.minimizedBar.style.width = mobile ? "100%" : `${MINIMIZED_WIDTH}px`;
	}

	_suggestCurrentPageContext({ force = false } = {}) {
		const identity = getPageContextIdentity();
		if (!identity || (!force && identity.type !== "document")) {
			this.store.clearPageContextSuggestion();
			this.store.cancelPageContextRequest();
			return;
		}
		this.store.offerPageContext(identity, { force });
	}

	show(trigger = null, { forceContext = false } = {}) {
		if (trigger) {
			this._lastTrigger = trigger;
		} else if (!this.open && document.activeElement && !this.root.contains(document.activeElement)) {
			this._lastTrigger = document.activeElement;
		}
		this._suggestCurrentPageContext({ force: forceContext });
		this._showPanel();
	}

	minimize() {
		if (!this.visible || this.minimized) return;
		this._hidePanelRoot();
		this.minimized = true;
		this._showMinimizedBar();
		this._syncAskButtons();
		this._persist();
	}

	hide() {
		this.minimized = false;
		this._hidePanelRoot();
		this._hideMinimizedBar();
		this._syncAskButtons();
		this._persist();
		this._restoreTriggerFocus();
	}

	toggle() {
		this.visible ? this.minimize() : this.show();
	}

	toggleFullscreen() {
		const next = !this.fullscreen;
		this.store.fullscreen.value = next;
		this._halfWidth = this._clampPanelWidth(this._halfWidth);
		this.root.style.width = next ? "100vw" : `${this._halfWidth}px`;
		this._persist();
	}

	_clampPanelWidth(width, reserve = 0) {
		const available = Math.max(240, window.innerWidth - reserve);
		const minimum = Math.min(MIN_WIDTH, available);
		return Math.min(available, Math.max(minimum, Number(width) || PANEL_WIDTH));
	}

	_resizePanelForViewport() {
		if (this.fullscreen) return;
		this._halfWidth = this._clampPanelWidth(this._halfWidth);
		this.root.style.width = `${this._halfWidth}px`;
		this._persist();
	}

	_syncAskButtons() {
		for (const button of document.querySelectorAll(`.${ASK_BUTTON_CLASS}`)) {
			button.setAttribute("aria-expanded", String(this.visible));
		}
	}

	_restoreTriggerFocus() {
		const fallback = window.cur_page?.page?.querySelector?.(`.${ASK_BUTTON_CLASS}`);
		const target = this._lastTrigger?.isConnected ? this._lastTrigger : fallback;
		target?.focus?.();
	}

	_persist() {
		writePanelState({
			open: this.open,
			minimized: this.minimized,
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
