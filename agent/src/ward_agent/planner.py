"""Planner: structured swap intent -> TxPlan quoted against the FTSO.

The quote mirrors Guardian._checkOracleFloor exactly: fair value from the same
oracle the chain enforces with, minOut = fair * (1 - slippage). What the agent
promises is precisely what the contract will check.
"""

import os
import time
from typing import Callable

from eth_abi import encode as abi_encode
from eth_utils import function_signature_to_4byte_selector
from pydantic import BaseModel, computed_field

from ward_agent import feeds
from ward_agent.envelope import SafetyEnvelope

SWAP_SIG = "swap(address,address,uint256)"

FtsoRead = Callable[[list[bytes]], list[tuple[int, int]]]


class TokenInfo(BaseModel):
    address: str
    decimals: int


class SwapIntent(BaseModel):
    user: str
    token_in: str  # symbol, e.g. "USDC"
    token_out: str  # symbol, e.g. "WFLR"
    amount_in: int  # raw units of token_in
    max_slippage_bps: int | None = None
    ttl_seconds: int | None = None


class TxPlan(BaseModel):
    user: str
    target: str
    function_sig: str
    token_in_symbol: str
    token_out_symbol: str
    token_in: str
    token_out: str
    amount_in: int
    fair_out: int  # FTSO fair value at quote time
    min_out: int
    feed_in: bytes
    feed_out: bytes
    max_slippage_bps: int
    ttl_seconds: int

    @computed_field
    @property
    def selector(self) -> bytes:
        return function_signature_to_4byte_selector(self.function_sig)

    def calldata(self) -> bytes:
        return self.selector + abi_encode(
            ["address", "address", "uint256"],
            [self.token_in, self.token_out, self.amount_in],
        )


def fair_value_out(
    amount_in: int,
    price_in: tuple[int, int],
    price_out: tuple[int, int],
    dec_token_in: int,
    dec_token_out: int,
) -> int:
    """Mirror of Guardian._checkOracleFloor math, including negative feed decimals."""
    value_in, feed_dec_in = price_in
    value_out, feed_dec_out = price_out
    num = amount_in * value_in * 10**dec_token_out
    den = value_out * 10**dec_token_in
    if feed_dec_out >= 0:
        num *= 10**feed_dec_out
    else:
        den *= 10 ** (-feed_dec_out)
    if feed_dec_in >= 0:
        den *= 10**feed_dec_in
    else:
        num *= 10 ** (-feed_dec_in)
    return num // den


class Planner:
    def __init__(
        self,
        tokens: dict[str, TokenInfo],
        dex_address: str,
        ftso_read: FtsoRead,
        default_slippage_bps: int = 50,
        default_ttl_seconds: int = 300,
    ):
        self.tokens = tokens
        self.dex_address = dex_address
        self.ftso_read = ftso_read
        self.default_slippage_bps = default_slippage_bps
        self.default_ttl_seconds = default_ttl_seconds

    def plan_swap(self, intent: SwapIntent) -> TxPlan:
        token_in = self.tokens[intent.token_in]
        token_out = self.tokens[intent.token_out]
        feed_in = feeds.BY_SYMBOL[intent.token_in]
        feed_out = feeds.BY_SYMBOL[intent.token_out]
        slippage = (
            intent.max_slippage_bps
            if intent.max_slippage_bps is not None
            else self.default_slippage_bps
        )
        ttl = intent.ttl_seconds if intent.ttl_seconds is not None else self.default_ttl_seconds

        price_in, price_out = self.ftso_read([feed_in, feed_out])
        fair = fair_value_out(
            intent.amount_in, price_in, price_out, token_in.decimals, token_out.decimals
        )
        min_out = fair * (10_000 - slippage) // 10_000

        return TxPlan(
            user=intent.user,
            target=self.dex_address,
            function_sig=SWAP_SIG,
            token_in_symbol=intent.token_in,
            token_out_symbol=intent.token_out,
            token_in=token_in.address,
            token_out=token_out.address,
            amount_in=intent.amount_in,
            fair_out=fair,
            min_out=min_out,
            feed_in=feed_in,
            feed_out=feed_out,
            max_slippage_bps=slippage,
            ttl_seconds=ttl,
        )


def build_envelope(plan: TxPlan, now: int | None = None, nonce: int | None = None) -> SafetyEnvelope:
    ts = now if now is not None else int(time.time())
    return SafetyEnvelope(
        user=plan.user,
        target=plan.target,
        selector=plan.selector,
        tokenIn=plan.token_in,
        maxAmountIn=plan.amount_in,
        tokenOut=plan.token_out,
        minOut=plan.min_out,
        feedIn=plan.feed_in,
        feedOut=plan.feed_out,
        maxSlippageBps=plan.max_slippage_bps,
        deadline=ts + plan.ttl_seconds,
        nonce=nonce if nonce is not None else int.from_bytes(os.urandom(32), "big"),
    )
