"""Common interface both LLM backends implement, so app.py never needs to
know whether it's talking to Claude's API or a local model."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .context import AppContext

SYSTEM_PROMPT = (
    "You are a helpful personal-finance assistant answering questions about the user's own "
    "financial data, which has already been parsed and categorized for you. Up to three sources "
    "may be loaded: categorized bank statement transactions, a personal finance-tracking sheet "
    "(investments, monthly budget, a property loan's EMI schedule), and an INDmoney portfolio "
    "snapshot (net worth, holdings, SIPs) -- use whichever tools are relevant, and say plainly "
    "when a source isn't loaded rather than guessing from what is. Use the provided tools to look "
    "up real numbers before answering -- never guess, round loosely, or estimate a figure you "
    "could look up. Amounts are in Indian Rupees (INR); format them like ₹12,345 or ₹1.2L for "
    "large numbers when it reads naturally. Be concise and specific, and mention the actual "
    "numbers the tools returned. If a question is ambiguous (e.g. no date range given), default "
    "to the full dataset and say so briefly. If a category name you guessed doesn't seem to "
    "exist, call list_categories to find the real one."
)


class LLMError(Exception):
    """Raised for any provider/config error the UI should show to the user."""


class LLMClient(ABC):
    @abstractmethod
    def ask(self, question: str, ctx: AppContext, history: list[dict]) -> str:
        """Run the tool-calling loop for one user question and return the
        assistant's final text reply. `history` is prior turns in whatever
        shape the concrete client expects (each implementation manages its
        own message format internally)."""
        raise NotImplementedError
