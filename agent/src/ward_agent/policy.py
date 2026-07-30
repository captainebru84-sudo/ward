"""Policy engine: the deterministic gate between a proposed plan and a signature.

Policies are private to the user — in TEE mode this file lives only inside the
enclave. The engine never mutates a plan; it either passes it or lists every
violated rule so the caller can see exactly why signing was refused.
"""

import json
from pathlib import Path

from eth_utils import function_signature_to_4byte_selector
from pydantic import BaseModel

from ward_agent.planner import TxPlan


class Policy(BaseModel):
    max_spend: dict[str, int] = {}  # token symbol -> max raw units per envelope
    allowed_targets: dict[str, list[str]] = {}  # target address -> allowed function sigs
    max_slippage_bps: int = 100
    max_deadline_seconds: int = 600

    def normalized_targets(self) -> dict[str, list[str]]:
        return {addr.lower(): sigs for addr, sigs in self.allowed_targets.items()}


class PolicyEngine:
    def __init__(self, policies: dict[str, Policy]):
        self.policies = policies

    @classmethod
    def from_file(cls, path: str | Path) -> "PolicyEngine":
        raw = json.loads(Path(path).read_text())
        return cls({name: Policy.model_validate(p) for name, p in raw.items()})

    def policy_for(self, user: str) -> Policy:
        return self.policies.get(user.lower()) or self.policies["default"]

    def check(self, plan: TxPlan) -> list[str]:
        """Return all violations; empty list means the plan may be signed."""
        p = self.policy_for(plan.user)
        violations: list[str] = []

        targets = p.normalized_targets()
        sigs = targets.get(plan.target.lower())
        if sigs is None:
            violations.append(f"target {plan.target} is not on the allowlist")
        else:
            allowed_selectors = {function_signature_to_4byte_selector(s) for s in sigs}
            if plan.selector not in allowed_selectors:
                violations.append(
                    f"function {plan.function_sig} is not allowed on {plan.target}"
                )

        cap = p.max_spend.get(plan.token_in_symbol)
        if cap is None:
            violations.append(f"no spend limit configured for {plan.token_in_symbol}")
        elif plan.amount_in > cap:
            violations.append(
                f"spend {plan.amount_in} exceeds {plan.token_in_symbol} cap {cap}"
            )

        if plan.max_slippage_bps > p.max_slippage_bps:
            violations.append(
                f"slippage {plan.max_slippage_bps}bps exceeds policy max {p.max_slippage_bps}bps"
            )

        if plan.ttl_seconds > p.max_deadline_seconds:
            violations.append(
                f"deadline ttl {plan.ttl_seconds}s exceeds policy max {p.max_deadline_seconds}s"
            )

        return violations
