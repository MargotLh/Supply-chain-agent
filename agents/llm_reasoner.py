"""Claude as the Decision Agent's reasoning step.

The deterministic scorer still builds and prices every option. Claude reads the
full situation, picks one of those options by index and explains why in language
an ops manager can act on. It cannot invent an option, change a cost, or approve
anything: the Decision Agent validates its answer and the approval policy is
applied in code afterwards.
"""
from __future__ import annotations

import json
import os

from pydantic import BaseModel

import settings

SYSTEM_PROMPT = """\
You are the Decision Agent in a supply chain exception workflow. An order is late and \
other agents have gathered the facts. You receive the order, the delay, and a list of \
mitigation options that a cost model has already priced. Each option's score is \
extra cost + days late x the customer tier's daily late penalty; lower is better.

Choose the option you would recommend to the operations manager. The lowest score is \
usually right, but weigh what the score cannot see: customer tier and relationship, how \
fragile a promise date is, how confident each estimate looks. If you choose an option \
other than the lowest score, say plainly why it is worth the difference.

You cannot approve spend. Company policy decides separately whether a human must sign \
off, so do not discuss approval. Write the rationale in two or three sentences of plain \
English for a busy ops manager: what to do, what it costs, and what it avoids."""


class LLMChoice(BaseModel):
    option_index: int   # index into the options list Claude was shown
    rationale: str


class ClaudeReasoner:
    def __init__(self, client=None, model: str | None = None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client = client
        self.model = model or settings.LLM_MODEL

    def choose(self, context: dict) -> LLMChoice:
        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=16000,
            output_config={"effort": "medium"},
            # On a safety decline the API re-runs the request on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(context, indent=2)}],
            output_format=LLMChoice,
        )
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"no usable answer from {self.model} (stop_reason={response.stop_reason})")
        return response.parsed_output


def default_reasoner() -> ClaudeReasoner | None:
    """Claude when DECISION_MODE allows it and credentials are present, else None (rules only)."""
    mode = settings.DECISION_MODE
    if mode == "rules":
        return None
    has_credentials = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    if mode == "llm" or has_credentials:
        return ClaudeReasoner()
    return None
