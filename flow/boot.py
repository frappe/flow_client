# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from flow.knowledge.extract import FILE_EXTENSIONS
from flow.permissions import has_flow_access


def boot_session(bootinfo):
	# Single source of truth for file types the ingest pipeline can extract
	bootinfo.flow_supported_file_types = sorted(FILE_EXTENSIONS)
	# Lets the panel skip mounting for users who may not use Flow. Presentation only —
	# `app_include_js` is assembled statically per site (frappe/www/desk.py), so the
	# bundle still ships to everyone. The real gate is flow.permissions on the API.
	bootinfo.flow_enabled = has_flow_access()
