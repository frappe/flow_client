# Copyright (c) 2026, Frappe Technologies and Contributors
# See license.txt

from copy import deepcopy
from unittest import TestCase

from litellm.llms.gemini.chat.transformation import GoogleAIStudioGeminiConfig
from litellm.llms.vertex_ai.gemini.transformation import _transform_request_body


class TestGeminiCompatibility(TestCase):
	def test_gemini_3_preserves_provider_ids_and_low_thinking(self):
		body = self._request("gemini-3.8-flash", {"reasoning_effort": "low"})
		call = body["contents"][1]["parts"][0]
		result = body["contents"][2]["parts"][0]["function_response"]
		self.assertEqual(call["function_call"]["id"], "provider_call_123")
		self.assertEqual(result["id"], "provider_call_123")
		self.assertEqual(result["name"], "echo")
		self.assertEqual(call["thoughtSignature"], "ZmFrZS1zaWduYXR1cmU=")
		self.assertEqual(body["generationConfig"]["thinkingConfig"]["thinkingLevel"], "low")

	def test_gemini_2_keeps_disabled_thinking_and_omits_native_ids(self):
		body = self._request("gemini-2.5-flash", {"thinking": {"type": "disabled", "budget_tokens": 0}})
		self.assertNotIn("id", body["contents"][1]["parts"][0]["function_call"])
		self.assertNotIn("id", body["contents"][2]["parts"][0]["function_response"])
		self.assertEqual(body["generationConfig"]["thinkingConfig"]["thinkingBudget"], 0)

	def _request(self, model, params):
		call_id = "provider_call_123__thought__ZmFrZS1zaWduYXR1cmU="
		messages = [
			{"role": "user", "content": "fake input"},
			{
				"role": "assistant",
				"tool_calls": [
					{"id": call_id, "type": "function", "function": {"name": "echo", "arguments": "{}"}}
				],
			},
			{"role": "tool", "tool_call_id": call_id, "content": "fake result"},
		]
		mapped = GoogleAIStudioGeminiConfig().map_openai_params(deepcopy(params), {}, model, False)
		return _transform_request_body(
			messages=messages,
			model=model,
			optional_params=mapped,
			custom_llm_provider="gemini",
			litellm_params={},
			cached_content=None,
		)
