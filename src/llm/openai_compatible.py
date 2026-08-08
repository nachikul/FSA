"""Any OpenAI-compatible chat endpoint: Ollama, LM Studio, vLLM, or the real
OpenAI API. Uses function calling when the model/server supports it; if a
call to the endpoint with `tools` fails outright (some local setups don't
implement it), falls back to stuffing a one-shot data summary into the
prompt so the app still degrades gracefully instead of erroring out."""
from __future__ import annotations

import json

from ..analysis import category_summary, headline_stats, monthly_summary
from ..sources.personal_sheet import section_totals
from .base import SYSTEM_PROMPT, LLMClient, LLMError
from .context import AppContext
from .tools import TOOLS, execute_tool

MAX_TOOL_ROUNDS = 6


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"] or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def _fallback_context(ctx: AppContext) -> str:
    """A compact, human-readable data summary for models that can't call tools."""
    parts = []
    df = ctx.transactions
    if df is not None and not df.empty:
        stats = headline_stats(df)
        spend = category_summary(df, "debit").round(2).to_dict(orient="records")
        income = category_summary(df, "credit").round(2).to_dict(orient="records")
        monthly = monthly_summary(df).round(2).to_dict(orient="records")
        parts.append(
            f"BANK SUMMARY: {json.dumps(stats, default=str)}\n"
            f"SPEND BY CATEGORY: {json.dumps(spend, default=str)}\n"
            f"INCOME BY CATEGORY: {json.dumps(income, default=str)}\n"
            f"MONTHLY: {json.dumps(monthly, default=str)}"
        )
    else:
        parts.append("No bank statements are loaded.")

    if ctx.portfolio is not None:
        p = ctx.portfolio
        parts.append(
            f"INDMONEY NET WORTH: invested={p.total_invested:.2f} current={p.total_current_value:.2f} "
            f"networth={p.total_networth:.2f} liabilities={p.liabilities_total:.2f}\n"
            f"BY ASSET TYPE: {json.dumps(p.by_asset_type.round(2).to_dict(orient='records'), default=str)}"
        )

    if ctx.sheet is not None and ctx.sheet.investments:
        parts.append(
            f"PERSONAL SHEET SECTION TOTALS: {json.dumps(section_totals(ctx.sheet.investments).round(2).to_dict(orient='records'), default=str)}"
        )

    parts.append(
        "(This is a pre-computed summary, not the raw data — answer from it as best you can "
        "and say so if the question needs row-level detail you don't have.)"
    )
    return "\n\n".join(parts)


class OpenAICompatibleClient(LLMClient):
    def __init__(self, base_url: str, model: str, api_key: str = ""):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise LLMError("The 'openai' package isn't installed.") from exc
        if not base_url:
            raise LLMError("No base URL provided for the local/OpenAI-compatible model.")
        if not model:
            raise LLMError("No model name provided.")
        self.client = OpenAI(base_url=base_url, api_key=api_key or "not-needed")
        self.model = model
        self._tools = _to_openai_tools(TOOLS)

    def ask(self, question: str, ctx: AppContext, history: list[dict]) -> str:
        try:
            return self._ask_with_tools(question, ctx, history)
        except Exception:
            return self._ask_fallback(question, ctx, history)

    def _ask_with_tools(self, question: str, ctx: AppContext, history: list[dict]) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history) + [
            {"role": "user", "content": question}
        ]

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self._tools,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                return msg.content or "(no response)"

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                }
            )
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = execute_tool(tc.function.name, args, ctx)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        return "I wasn't able to finish looking that up in a reasonable number of steps — try a narrower question."

    def _ask_fallback(self, question: str, ctx: AppContext, history: list[dict]) -> str:
        context = _fallback_context(ctx)
        messages = (
            [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + context}]
            + list(history)
            + [{"role": "user", "content": question}]
        )
        try:
            response = self.client.chat.completions.create(model=self.model, messages=messages)
        except Exception as exc:
            raise LLMError(f"Could not reach the model at this base URL: {exc}") from exc
        return response.choices[0].message.content or "(no response)"
