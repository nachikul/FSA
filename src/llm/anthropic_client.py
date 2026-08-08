"""Claude via the official Anthropic API, using native tool use so the model
grounds its answers in real query results against your data."""
from __future__ import annotations

import pandas as pd

from .base import SYSTEM_PROMPT, LLMClient, LLMError
from .tools import TOOLS, execute_tool

MAX_TOOL_ROUNDS = 6


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("The 'anthropic' package isn't installed.") from exc
        if not api_key:
            raise LLMError("No Anthropic API key provided.")
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def ask(self, question: str, df: pd.DataFrame, history: list[dict]) -> str:
        messages = list(history) + [{"role": "user", "content": question}]

        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=1500,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=messages,
                )
            except self._anthropic.APIError as exc:
                raise LLMError(f"Anthropic API error: {exc}") from exc

            if response.stop_reason != "tool_use":
                text = "".join(block.text for block in response.content if block.type == "text")
                return text or "(no response)"

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input, df)
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
            messages.append({"role": "user", "content": tool_results})

        return "I wasn't able to finish looking that up in a reasonable number of steps — try a narrower question."
