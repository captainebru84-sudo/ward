"""Natural-language intent layer.

Gemini turns free text into a structured IntentDraft — and nothing else. It
never sees keys, addresses, prices, or policies. The draft is converted
deterministically into a SwapIntent and then walks the same
planner -> policy -> signer path as any structured request: the model
proposes, the policy engine disposes.
"""

from decimal import Decimal, InvalidOperation
from typing import Callable, Literal

from pydantic import BaseModel

from ward_agent.config import Settings
from ward_agent.planner import SwapIntent, TokenInfo


class IntentDraft(BaseModel):
    action: Literal["swap", "unsupported"]
    token_in: str = ""
    token_out: str = ""
    amount: str = ""  # human units of token_in, decimal string, verbatim from the user
    max_slippage_bps: int | None = None
    reason: str = ""


class UnsupportedIntent(Exception):
    pass


CompleteFn = Callable[[str], IntentDraft]


def build_system_prompt(tokens: dict[str, TokenInfo]) -> str:
    symbols = ", ".join(sorted(tokens))
    return (
        "You convert a user's natural-language DeFi request into a strict swap intent.\n"
        f"Known tokens: {symbols}.\n"
        "Rules:\n"
        "- Only a single simple swap between two different known tokens is supported.\n"
        "- amount is the human-readable amount of token_in as a decimal string, exactly as"
        " the user stated it. Never invent, infer, or convert amounts.\n"
        "- If the user states a slippage tolerance, express it in basis points in"
        " max_slippage_bps (1% = 100); otherwise leave it null.\n"
        "- Anything else — transfers, approvals, withdrawals, multi-step plans, unknown"
        " tokens, missing amounts, ambiguity — is action=unsupported with a short reason.\n"
    )


class IntentParser:
    def __init__(self, complete: CompleteFn, tokens: dict[str, TokenInfo]):
        self._complete = complete
        self._tokens = tokens

    def parse(self, user: str, text: str) -> tuple[SwapIntent, IntentDraft]:
        draft = self._complete(text)
        if draft.action != "swap":
            raise UnsupportedIntent(draft.reason or "not a supported swap request")
        token_in = draft.token_in.upper()
        token_out = draft.token_out.upper()
        for sym in (token_in, token_out):
            if sym not in self._tokens:
                raise UnsupportedIntent(f"unknown token: {sym or '<missing>'}")
        if token_in == token_out:
            raise UnsupportedIntent("token_in and token_out are the same")
        try:
            amount = Decimal(draft.amount)
        except InvalidOperation:
            raise UnsupportedIntent(f"unparseable amount: {draft.amount!r}")
        if amount <= 0:
            raise UnsupportedIntent("amount must be positive")
        raw = int(amount * 10 ** self._tokens[token_in].decimals)
        intent = SwapIntent(
            user=user,
            token_in=token_in,
            token_out=token_out,
            amount_in=raw,
            max_slippage_bps=draft.max_slippage_bps,
        )
        return intent, draft


def gemini_complete(settings: Settings, system_prompt: str) -> CompleteFn:
    from google import genai
    from google.genai import types

    if settings.gemini_api_key:
        client = genai.Client(api_key=settings.gemini_api_key)
    elif settings.gemini_vertex:
        client = genai.Client(
            vertexai=True, project=settings.gcp_project, location=settings.gcp_location
        )
    else:
        raise RuntimeError("intent layer not configured: set WARD_GEMINI_API_KEY or WARD_GEMINI_VERTEX")

    def complete(text: str) -> IntentDraft:
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=IntentDraft,
                temperature=0,
            ),
        )
        if isinstance(resp.parsed, IntentDraft):
            return resp.parsed
        return IntentDraft.model_validate_json(resp.text or "")

    return complete
