<script setup>
import { ref, computed, watch, nextTick } from "vue";
import PanelDropdown from "./PanelDropdown.vue";
import AttachmentChip from "./AttachmentChip.vue";
import { Button, FeatherIcon } from "@/lib/ui";
import { getPageContext, getPageContextIdentity } from "@/lib/pageContext";
import { useStore } from "@/store";
import { __ } from "@/lib/translate";

const {
	agents,
	models,
	selectedAgent,
	selectedModel,
	attachments,
	sending,
	paused,
	locked,
	loaded,
	needsSetup,
	uploading,
	focusTick,
	pageContextRequest,
	pageContextSuggestion,
	agentLabel,
	modelLabel,
	setAgent,
	setModel,
	armPageContext,
	acceptPageContextSuggestion,
	cancelPageContextRequest,
	dismissPageContextSuggestion,
	markPageContextAttached,
	send,
	stopRun,
	attachFiles,
	removeAttachment,
} = useStore();

// Backend (flow/boot.py) is the single source of truth for supported file types.
const ACCEPT = computed(() =>
	(frappe.boot.flow_supported_file_types || []).map((ext) => `.${ext}`).join(",")
);

const text = ref("");
const el = ref(null);
const fileInput = ref(null);
const dragging = ref(false);

const inputDisabled = computed(
	() => !loaded.value || sending.value || paused.value || needsSetup.value
);

const agentItems = computed(() => agents.value.map((a) => ({ value: a.name, label: a.title })));
const modelItems = computed(() => [
	{ value: null, label: __("Default") },
	...models.value.map((m) => ({ value: m.name, label: m.title })),
]);

const canSend = computed(() => text.value.trim() && !inputDisabled.value && !uploading.value);
const placeholder = computed(() => {
	if (!loaded.value) return __("Loading…");
	if (needsSetup.value) return __("Setup required…");
	return __("Ask {0}…", [agentLabel(selectedAgent.value)]);
});

const includePageContext = ref(false);

function submit() {
	if (!canSend.value) return;

	const identity = getPageContextIdentity();
	const pageContext =
		includePageContext.value && pageContextRequest.value?.key === identity?.key
			? getPageContext()
			: null;
	send(text.value, { pageContext });
	if (pageContext) markPageContextAttached(identity);
	else cancelPageContextRequest();

	text.value = "";
	includePageContext.value = false;

	nextTick(resize);
}

function pickFiles() {
	fileInput.value?.click();
}

function onFilesPicked(e) {
	attachFiles(e.target.files);
	e.target.value = ""; // allow re-picking the same file
}

function onDragOver(e) {
	if (inputDisabled.value) return;
	e.preventDefault();
	dragging.value = true;
}

function onDragLeave(e) {
	if (e.currentTarget.contains(e.relatedTarget)) return;
	dragging.value = false;
}

function onDrop(e) {
	e.preventDefault();
	dragging.value = false;
	if (inputDisabled.value) return;
	attachFiles(e.dataTransfer.files);
}

function onKeydown(e) {
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault();
		submit();
	}
}

function resize() {
	const t = el.value;
	if (!t) return;
	t.style.height = "auto";
	t.style.height = `${Math.min(t.scrollHeight, 160)}px`;
}

function togglePageContext() {
	if (includePageContext.value) {
		cancelPageContextRequest();
		return;
	}
	if (pageContextSuggestion.value) {
		acceptPageContextSuggestion();
		return;
	}
	armPageContext(getPageContextIdentity());
}

watch(pageContextRequest, (request) => {
	includePageContext.value = Boolean(request);
});
watch(focusTick, () => nextTick(() => el.value?.focus()));
</script>

<template>
	<div
		class="flow-composer absolute inset-x-5 bottom-3.5 mx-auto flex max-w-3xl flex-col gap-1.5 rounded-xl border bg-surface-white px-2.5 py-2 shadow-sm transition-[border-color,background-color] focus-within:border-outline-gray-3"
		:class="dragging ? 'border-outline-gray-4 bg-surface-gray-1' : 'border-outline-gray-2'"
		@dragover="onDragOver"
		@dragleave="onDragLeave"
		@drop="onDrop"
	>
		<div
			v-if="pageContextSuggestion"
			class="flex items-center gap-2 rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-2.5 py-2 text-xs text-ink-gray-7"
		>
			<FeatherIcon name="map-pin" class="h-3.5 w-3.5 shrink-0 text-ink-gray-6" />
			<span class="min-w-0 flex-1 truncate">
				{{ __("New page: {0}", [pageContextSuggestion.label]) }}
			</span>
			<button
				type="button"
				class="shrink-0 font-medium text-ink-gray-9 hover:underline disabled:opacity-50"
				:disabled="inputDisabled"
				@click="acceptPageContextSuggestion"
			>
				{{ __("Add context") }}
			</button>
			<button
				type="button"
				class="flex h-5 w-5 shrink-0 items-center justify-center rounded hover:bg-surface-gray-3"
				:title="__('Dismiss')"
				@click="dismissPageContextSuggestion"
			>
				<FeatherIcon name="x" class="h-3 w-3" />
			</button>
		</div>

		<div v-if="attachments.length" class="flex flex-wrap gap-1.5">
			<AttachmentChip
				v-for="a in attachments"
				:key="a.uid"
				:file-name="a.file_name"
				:file-size="a.file_size"
				:status="a.status"
				:error="a.error"
				removable
				@remove="removeAttachment(a.uid)"
			/>
		</div>

		<textarea
			ref="el"
			v-model="text"
			rows="1"
			:placeholder="placeholder"
			:disabled="inputDisabled"
			class="max-h-40 min-h-[50px] w-full resize-none border-0 bg-transparent text-base font-normal leading-relaxed text-ink-gray-9 outline-none placeholder:text-ink-gray-4"
			@keydown="onKeydown"
			@input="resize"
		></textarea>

		<div class="flex items-center gap-1.5">
			<!-- attach -->
			<button
				class="flex h-6 w-6 items-center justify-center rounded text-ink-gray-6 hover:bg-surface-gray-2 disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
				:disabled="inputDisabled"
				:title="__('Attach file')"
				@click="pickFiles"
			>
				<FeatherIcon name="paperclip" class="h-3.5 w-3.5" />
			</button>
			<input
				ref="fileInput"
				type="file"
				multiple
				:accept="ACCEPT"
				class="hidden"
				@change="onFilesPicked"
			/>

			<!-- page context -->
			<button
				class="flex h-6 items-center gap-1 rounded px-1.5 text-[12.5px] disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
				:class="
					includePageContext
						? 'bg-surface-gray-2 text-ink-gray-9'
						: 'text-ink-gray-6 hover:bg-surface-gray-2'
				"
				:disabled="inputDisabled"
				:title="
					includePageContext
						? __('Remove page context')
						: __('Include page context')
				"
				@click="togglePageContext"
			>
				<FeatherIcon
					:name="includePageContext ? 'check-circle' : 'link'"
					class="h-3.5 w-3.5"
				/>
				<span>{{ __("Context") }}</span>
			</button>

			<!-- agent -->
			<PanelDropdown
				:items="agentItems"
				:model-value="selectedAgent"
				:disabled="locked"
				searchable
				@update:model-value="setAgent"
			>
				<template #trigger="{ toggle }">
					<button
						class="flex h-6 items-center gap-1 rounded px-1.5 text-[12.5px] text-ink-gray-6 hover:bg-surface-gray-2 disabled:cursor-default disabled:hover:bg-transparent"
						:disabled="locked"
						:title="__('Agent')"
						@click="toggle"
					>
						<span class="font-medium text-ink-gray-8">{{
							agentLabel(selectedAgent)
						}}</span>
						<FeatherIcon v-if="!locked" name="chevron-down" class="h-3 w-3" />
					</button>
				</template>
			</PanelDropdown>

			<span class="text-ink-gray-3">/</span>

			<!-- model -->
			<PanelDropdown
				:items="modelItems"
				:model-value="selectedModel"
				searchable
				@update:model-value="setModel"
			>
				<template #trigger="{ toggle }">
					<button
						class="flex h-6 items-center gap-1 rounded px-1.5 text-[12.5px] text-ink-gray-6 hover:bg-surface-gray-2"
						:title="__('Model')"
						@click="toggle"
					>
						<span class="font-medium text-ink-gray-8">
							{{ modelLabel(selectedModel) || __("Default") }}
						</span>
						<FeatherIcon name="chevron-down" class="h-3 w-3" />
					</button>
				</template>
			</PanelDropdown>

			<span class="flex-1"></span>

			<Button
				v-if="sending"
				theme="red"
				class="!bg-surface-red-3 hover:!bg-surface-red-4"
				:title="__('Stop')"
				@click="stopRun"
			>
				<template #icon
					><span class="h-2.5 w-2.5 rounded-[2px] bg-current"></span
				></template>
			</Button>
			<Button
				v-else
				variant="solid"
				:disabled="!canSend"
				:title="__('Send')"
				@click="submit"
			>
				<template #icon><FeatherIcon name="arrow-up" class="h-4 w-4" /></template>
			</Button>
		</div>
	</div>
</template>
