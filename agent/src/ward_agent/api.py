"""Agent service + FastAPI surface.

POST /envelope is the whole product: intent in, either a signed Safety
Envelope out or a 403 listing every policy rule the plan violated.
"""

from fastapi import FastAPI, HTTPException

from ward_agent.chain import FtsoReader, get_w3
from ward_agent.config import Settings, get_settings
from ward_agent.envelope import SafetyEnvelope
from ward_agent.planner import Planner, SwapIntent, TokenInfo, TxPlan, build_envelope
from ward_agent.policy import PolicyEngine
from ward_agent.signer import WardSigner

import json
from pathlib import Path


class PolicyRefusal(Exception):
    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("; ".join(violations))


class AgentService:
    def __init__(
        self,
        planner: Planner,
        policy: PolicyEngine,
        signer: WardSigner,
        chain_id: int,
        guardian: str,
    ):
        self.planner = planner
        self.policy = policy
        self.signer = signer
        self.chain_id = chain_id
        self.guardian = guardian

    def handle_swap(self, intent: SwapIntent) -> dict:
        plan = self.planner.plan_swap(intent)
        violations = self.policy.check(plan)
        if violations:
            raise PolicyRefusal(violations)
        env = build_envelope(plan)
        sig = self.signer.sign_envelope(env, self.chain_id, self.guardian)
        return self._response(plan, env, sig)

    def _response(self, plan: TxPlan, env: SafetyEnvelope, sig: bytes) -> dict:
        return {
            "envelope": env.as_json(),
            "signature": "0x" + sig.hex(),
            "calldata": "0x" + plan.calldata().hex(),
            "guardian": self.guardian,
            "chainId": self.chain_id,
            "quote": {
                "fairOut": str(plan.fair_out),
                "minOut": str(plan.min_out),
                "maxSlippageBps": plan.max_slippage_bps,
                "pair": f"{plan.token_in_symbol}->{plan.token_out_symbol}",
            },
        }


def build_service(settings: Settings | None = None) -> AgentService:
    s = settings or get_settings()
    raw_tokens = json.loads(Path(s.tokens_path).read_text())
    tokens = {sym: TokenInfo.model_validate(t) for sym, t in raw_tokens.items()}
    w3 = get_w3(s.rpc_url)
    planner = Planner(
        tokens=tokens,
        dex_address=s.dex_address,
        ftso_read=FtsoReader(w3).read,
        default_ttl_seconds=s.envelope_ttl_seconds,
    )
    policy = PolicyEngine.from_file(s.policies_path)
    signer = WardSigner.from_key_or_ephemeral(s.signer_key)
    return AgentService(planner, policy, signer, s.chain_id, s.guardian_address)


def create_app(service: AgentService | None = None) -> FastAPI:
    app = FastAPI(title="Ward Agent", version="0.1.0")
    svc = service or build_service()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "chainId": svc.chain_id, "guardian": svc.guardian}

    @app.get("/signer")
    def signer() -> dict:
        return {"address": svc.signer.address, "ephemeral": svc.signer.ephemeral}

    @app.post("/envelope")
    def envelope(intent: SwapIntent) -> dict:
        try:
            return svc.handle_swap(intent)
        except PolicyRefusal as e:
            raise HTTPException(status_code=403, detail={"violations": e.violations})
        except KeyError as e:
            raise HTTPException(status_code=400, detail=f"unknown token or feed: {e}")

    return app
