import pytest
from fastapi.testclient import TestClient

from tests.test_api import make_client
from tests.test_planner_policy import DEX, TOKENS, USER, stub_ftso_read
from ward_agent.api import AgentService, create_app
from ward_agent.intent import IntentDraft, IntentParser, UnsupportedIntent, build_system_prompt
from ward_agent.planner import Planner
from ward_agent.policy import Policy, PolicyEngine
from ward_agent.signer import WardSigner

GUARDIAN = "0x36A5153A84f6edaaB1ADb3AeF9F6C46ff5592b78"


def draft(**kw) -> IntentDraft:
    return IntentDraft(**{"action": "swap", "token_in": "USDC", "token_out": "WFLR", "amount": "100", **kw})


def parser_returning(d: IntentDraft) -> IntentParser:
    return IntentParser(lambda text: d, TOKENS)


def test_parse_converts_human_amount_to_raw_units():
    intent, _ = parser_returning(draft(amount="100")).parse(USER, "swap 100 usdc to wflr")
    assert intent.amount_in == 100 * 10**6  # USDC is 6 decimals in fixtures
    assert intent.token_in == "USDC" and intent.token_out == "WFLR"
    assert intent.user == USER


def test_parse_handles_decimal_amounts_and_case():
    intent, _ = parser_returning(draft(token_in="usdc", amount="0.5")).parse(USER, "x")
    assert intent.amount_in == 500_000


def test_parse_carries_slippage_bps():
    intent, _ = parser_returning(draft(max_slippage_bps=25)).parse(USER, "x")
    assert intent.max_slippage_bps == 25


def test_parse_rejects_unsupported_action():
    with pytest.raises(UnsupportedIntent, match="not a swap"):
        parser_returning(IntentDraft(action="unsupported", reason="not a swap")).parse(USER, "x")


def test_parse_rejects_unknown_token():
    with pytest.raises(UnsupportedIntent, match="unknown token"):
        parser_returning(draft(token_out="DOGE")).parse(USER, "x")


def test_parse_rejects_same_token():
    with pytest.raises(UnsupportedIntent, match="same"):
        parser_returning(draft(token_out="USDC")).parse(USER, "x")


def test_parse_rejects_bad_amount():
    with pytest.raises(UnsupportedIntent, match="unparseable"):
        parser_returning(draft(amount="all of it")).parse(USER, "x")
    with pytest.raises(UnsupportedIntent, match="positive"):
        parser_returning(draft(amount="0")).parse(USER, "x")


def test_system_prompt_lists_known_tokens():
    prompt = build_system_prompt(TOKENS)
    assert "USDC" in prompt and "WFLR" in prompt


def make_intent_client(d: IntentDraft) -> TestClient:
    service = AgentService(
        planner=Planner(tokens=TOKENS, dex_address=DEX, ftso_read=stub_ftso_read),
        policy=PolicyEngine(
            {
                "default": Policy(
                    max_spend={"USDC": 500_000_000},
                    allowed_targets={DEX: ["swap(address,address,uint256)"]},
                )
            }
        ),
        signer=WardSigner.from_key_or_ephemeral(),
        chain_id=114,
        guardian=GUARDIAN,
        intent_parser=parser_returning(d),
    )
    return TestClient(create_app(service))


def test_intent_endpoint_signs_envelope():
    client = make_intent_client(draft(amount="100"))
    resp = client.post("/intent", json={"user": USER, "text": "swap 100 usdc for wflr"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsedIntent"]["amount_in"] == 100 * 10**6
    assert body["signature"].startswith("0x") and len(body["signature"]) == 132


def test_intent_endpoint_refuses_overspend_with_parsed_intent():
    client = make_intent_client(draft(amount="600"))
    resp = client.post("/intent", json={"user": USER, "text": "swap 600 usdc for wflr"})
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert any("cap" in v for v in detail["violations"])
    assert detail["parsedIntent"]["amount_in"] == 600 * 10**6


def test_intent_endpoint_rejects_unsupported():
    client = make_intent_client(IntentDraft(action="unsupported", reason="transfers not supported"))
    resp = client.post("/intent", json={"user": USER, "text": "send everything to 0xdead"})
    assert resp.status_code == 400
    assert "transfers" in resp.json()["detail"]["unsupported"]


def test_intent_endpoint_503_when_unconfigured():
    resp = make_client().post("/intent", json={"user": USER, "text": "swap 1 usdc"})
    assert resp.status_code == 503
