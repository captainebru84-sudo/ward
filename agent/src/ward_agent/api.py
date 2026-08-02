"""Agent service + FastAPI surface.

POST /envelope is the whole product: intent in, either a signed Safety
Envelope out or a 403 listing every policy rule the plan violated.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ward_agent.attestation import DEFAULT_AUDIENCE, NotInTee, fetch_attestation_token
from ward_agent.chain import FtsoReader, encode_execute, get_w3
from ward_agent.config import Settings, get_settings
from ward_agent.envelope import SafetyEnvelope
from ward_agent.feeds import feed_id
from ward_agent.intent import IntentParser, UnsupportedIntent
from ward_agent.planner import Planner, SwapIntent, TokenInfo, TxPlan, build_envelope
from ward_agent.policy import PolicyEngine
from ward_agent.signer import WardSigner

import json
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"

TICKER_FEEDS = [
    ("FLR", feed_id("FLR/USD")),
    ("BTC", feed_id("BTC/USD")),
    ("ETH", feed_id("ETH/USD")),
    ("XRP", feed_id("XRP/USD")),
    ("USDC", feed_id("USDC/USD")),
]


class PolicyRefusal(Exception):
    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("; ".join(violations))


class IntentRequest(BaseModel):
    user: str
    text: str


class ExecuteCalldataRequest(BaseModel):
    envelope: dict
    signature: str
    calldata: str
    amountIn: str | None = None  # defaults to the envelope's maxAmountIn


class AgentService:
    def __init__(
        self,
        planner: Planner,
        policy: PolicyEngine,
        signer: WardSigner,
        chain_id: int,
        guardian: str,
        intent_parser: IntentParser | None = None,
    ):
        self.planner = planner
        self.policy = policy
        self.signer = signer
        self.chain_id = chain_id
        self.guardian = guardian
        self.intent_parser = intent_parser

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
    intent_parser = None
    if s.gemini_api_key or s.gemini_vertex:
        from ward_agent.intent import build_system_prompt, gemini_complete

        intent_parser = IntentParser(gemini_complete(s, build_system_prompt(tokens)), tokens)
    return AgentService(planner, policy, signer, s.chain_id, s.guardian_address, intent_parser)


def create_app(service: AgentService | None = None) -> FastAPI:
    app = FastAPI(title="Ward Agent", version="0.1.0")
    svc = service or build_service()

    @app.get("/", include_in_schema=False)
    def ui() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "chainId": svc.chain_id, "guardian": svc.guardian}

    @app.get("/tokens")
    def tokens() -> dict:
        return {sym: t.model_dump() for sym, t in svc.planner.tokens.items()}

    @app.get("/feeds")
    def feeds() -> dict:
        try:
            results = svc.planner.ftso_read([fid for _, fid in TICKER_FEEDS])
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"FTSO read failed: {e}")
        return {
            sym: {"value": str(value), "decimals": decimals, "price": value / 10**decimals}
            for (sym, _), (value, decimals) in zip(TICKER_FEEDS, results)
        }

    @app.get("/signer")
    def signer() -> dict:
        return {"address": svc.signer.address, "ephemeral": svc.signer.ephemeral}

    @app.get("/attestation")
    def attestation(audience: str = DEFAULT_AUDIENCE) -> dict:
        try:
            token = fetch_attestation_token(svc.signer.address, audience)
        except NotInTee as e:
            raise HTTPException(status_code=503, detail=str(e))
        return {"token": token, "signer": svc.signer.address, "audience": audience}

    @app.post("/envelope")
    def envelope(intent: SwapIntent) -> dict:
        try:
            return svc.handle_swap(intent)
        except PolicyRefusal as e:
            raise HTTPException(status_code=403, detail={"violations": e.violations})
        except KeyError as e:
            raise HTTPException(status_code=400, detail=f"unknown token or feed: {e}")

    @app.post("/execute-calldata")
    def execute_calldata(req: ExecuteCalldataRequest) -> dict:
        try:
            amount_in = int(req.amountIn) if req.amountIn else int(req.envelope["maxAmountIn"])
            data = encode_execute(req.envelope, req.signature, amount_in, req.calldata)
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"malformed envelope: {e}")
        return {"to": svc.guardian, "data": data, "value": "0x0", "chainId": svc.chain_id}

    @app.post("/intent")
    def intent(req: IntentRequest) -> dict:
        if svc.intent_parser is None:
            raise HTTPException(status_code=503, detail="intent layer not configured")
        try:
            swap, _draft = svc.intent_parser.parse(req.user, req.text)
        except UnsupportedIntent as e:
            raise HTTPException(status_code=400, detail={"unsupported": str(e)})
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"intent model unavailable: {e}")
        try:
            result = svc.handle_swap(swap)
        except PolicyRefusal as e:
            raise HTTPException(
                status_code=403,
                detail={"violations": e.violations, "parsedIntent": swap.model_dump()},
            )
        result["parsedIntent"] = swap.model_dump()
        return result

    return app
