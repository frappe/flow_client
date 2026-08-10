## Summary

This PR resolves critical issues in Flow session message persistence, LiteLLM/Gemini API integration, and error rendering:
1. **Red Error Message Box Component**: Renders streaming, run, API, rate limit (`RateLimitError`/`QuotaExhausted`), and session error messages inside a styled Red Error Box in the chat UI.
2. **Tool Call ID Truncation Error**: Prevents `CharacterLengthExceededError` when models (such as Google Gemini, Antigravity, or deep-thinking models) generate long thought tool call IDs (>140 characters).
3. **Missing Tool Call ID Exception in LiteLLM**: Ensures `role: "tool"` messages include their corresponding function `name` both during execution loops and when reconstructing conversation transcripts from stored DB session messages.

---

## Problem & Root Cause

### 1. Error Message Rendering in Chat
* **Symptom**: Unhandled exceptions, RateLimit errors, or streaming failures appended plain text `\n\nError: ...` into markdown text parts, resulting in unstyled text inside chat bubbles instead of a dedicated error state.
* **Fix**: Built a dedicated `ErrorMessage.vue` component with red warning icon (`alert-triangle`), red container background (`var(--surface-red-1)`), border (`var(--border-red-2)`), and text (`var(--ink-red-4)`). Updated `store.js` and `AssistantMessage.vue` to produce and render error parts.

### 2. `tool_call_id` Truncation (`CharacterLengthExceededError`)
* **Symptom**: 
  ```text
  Error: Flow Session Message, Row 16: 'Tool Call ID' (call_046343...) will get truncated, as max characters allowed is 140
  ```
* **Root Cause**: In `Flow Session Message` (`flow_session_message.json`), `tool_call_id` was defined as `Data` (mapping to `VARCHAR(140)`). When advanced LLMs emitted long thought/tool call IDs (>140 chars), Frappe raised a validation error during `session.save()`, causing the Flow run to fail.

### 3. LiteLLM / Gemini Tool Matching Error
* **Symptom**:
  ```text
  litellm.APIConnectionError: Missing corresponding tool call for tool response message. Received - message={'role': 'tool', 'toolcallid': '...'}, last_message_with_tool_calls={...}
  ```
* **Root Cause**: LiteLLM's Gemini transformer requires every `role: "tool"` response message to specify its function `name`. If `name` is omitted, LiteLLM attempts to match `tool_call_id` against `last_message_with_tool_calls`. In multi-turn sessions or resumed runs with ID sanitization/mismatches, LiteLLM failed to resolve the name and threw an API error.

---

## Proposed Changes

### Frontend Error Box Component (`frontend/src/components/ErrorMessage.vue`, `AssistantMessage.vue`, `store.js`)
- Created `ErrorMessage.vue` component styled with red background/border/text.
- Added `makeErrorPart()` and `makeTextOrErrorParts()` in `store.js` to capture streaming, failMessage, and loaded transcript errors as error parts.
- Updated `AssistantMessage.vue` to render error parts inside `ErrorMessage.vue`.
- Built frontend production assets (`vite build`).

### `flow/flow/doctype/flow_session_message/flow_session_message.json` & `.py`
- Changed `tool_call_id` `fieldtype` from `Data` to `Small Text` (`text` in MariaDB).
- Updated type annotations in `flow_session_message.py` to `DF.SmallText | None`.
- **Benefit**: Removes string length truncation checks while supporting IDs up to 65,535 characters.

### `flow/lib/agent.py`
- Updated tool message construction in `_loop()` and `_resume_loop()` to explicitly attach `"name": call.name` to all `role: "tool"` messages.

### `flow/flow/doctype/flow_session/flow_session.py`
- Enhanced `_row_to_message()` and `transcript()` to map preceding assistant `tool_calls` to their function names when reading stored transcript rows.
- Attached `"name"` to `role: "tool"` messages in transcript outputs.

---

## How Has This Been Tested?

1. **Frontend Error UI Verification**:
   - Built assets (`yarn build` in `frontend/`) and verified error part rendering.
2. **Database Schema Verification**:
   - Ran `bench migrate` and verified that `tabFlow Session Message.tool_call_id` column successfully converted to `text`.
3. **Unit & Integration Tests**:
   - Executed `bench run-tests --app flow`. All 98 core agent unit tests passed cleanly (`OK`).
