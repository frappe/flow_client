const MAX_LIST_ROWS = 50;
const MAX_LIST_FIELDS = 60;
const MAX_PAGE_TEXT_CHARS = 50_000;

export function getPageContextIdentity() {
	const route = frappe.get_route?.() || [];
	const [view, doctype, name] = route;

	if (view === "Form" && doctype && name) {
		return {
			type: "document",
			key: `document:${doctype}:${name}`,
			label: `${doctype} ${name}`,
		};
	}
	if (view === "List" && doctype) {
		return {
			type: "list",
			key: `list:${doctype}`,
			label: `${doctype} List`,
		};
	}
	const routeLabel = route.filter(Boolean).join(" / ");
	return routeLabel
		? { type: "route", key: `route:${JSON.stringify(route)}`, label: routeLabel }
		: null;
}

export function getPageContext() {
	const route = frappe.get_route?.() || [];
	const [view, routeDoctype, routeName] = route;
	const frm = window.cur_frm;

	if (
		view === "Form" &&
		frm?.doctype === routeDoctype &&
		String(frm?.docname) === String(routeName)
	) {
		return {
			type: "document",
			doctype: frm.doctype,
			name: frm.docname,
			is_new: Boolean(frm.is_new?.() || frm.doc?.__islocal),
			is_dirty: Boolean(frm.is_dirty?.()),
			values: snapshotDocument(frm.doc),
			route,
		};
	}

	const list = window.cur_list;
	if (view === "List" && list?.doctype === routeDoctype) {
		const rows = Array.isArray(list.data) ? list.data : [];
		return {
			type: "list",
			doctype: list.doctype,
			filters: list.filter_area?.get?.() || [],
			names: rows.map((row) => row?.name).filter(Boolean).slice(0, MAX_LIST_ROWS),
			fields: listFields(rows),
			route,
		};
	}

	return {
		type: "route",
		route,
		page_text: visiblePageText(),
	};
}

function snapshotDocument(doc) {
	if (!doc || typeof doc !== "object") return {};
	return Object.fromEntries(
		Object.entries(doc).filter(([fieldname]) => !fieldname.startsWith("__"))
	);
}

function listFields(rows) {
	const fields = new Set(["name"]);
	for (const row of rows.slice(0, MAX_LIST_ROWS)) {
		if (!row || typeof row !== "object") continue;
		for (const fieldname of Object.keys(row)) {
			if (!fieldname.startsWith("_") && fields.size < MAX_LIST_FIELDS) {
				fields.add(fieldname);
			}
		}
	}
	return [...fields];
}

function visiblePageText() {
	// Frappe's Desk Container keeps the active DOM page on `cur_page.page`; previously
	// visited pages remain mounted but hidden, so a generic selector can capture stale text.
	const element = window.cur_page?.page;
	return (element?.innerText || "").trim().slice(0, MAX_PAGE_TEXT_CHARS);
}
