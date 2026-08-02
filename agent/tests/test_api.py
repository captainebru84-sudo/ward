from fastapi.testclient import TestClient

from tests.test_planner_policy import DEX, TOKENS, USER, stub_ftso_read
from ward_agent.api import AgentService, create_app
from ward_agent.planner import Planner
from ward_agent.policy import Policy, PolicyEngine
from ward_agent.signer import WardSigner

GUARDIAN = "0x5FCDc267ca392B64362957b7FD021719466d1775"


def make_client() -> TestClient:
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
    )
    return TestClient(create_app(service))


def test_health_and_signer():
    client = make_client()
    assert client.get("/health").json()["guardian"] == GUARDIAN
    signer = client.get("/signer").json()
    assert signer["ephemeral"] is True
    assert signer["address"].startswith("0x")


def test_ui_and_tokens():
    client = make_client()
    page = client.get("/")
    assert page.status_code == 200
    assert "Safety Envelope" in page.text
    toks = client.get("/tokens").json()
    assert toks["USDC"]["decimals"] == TOKENS["USDC"].decimals


def test_feeds_returns_ticker_prices():
    client = make_client()
    feeds = client.get("/feeds").json()
    assert "FLR" in feeds
    assert float(feeds["FLR"]["price"]) > 0


def test_attestation_unavailable_outside_tee():
    client = make_client()
    resp = client.get("/attestation")
    assert resp.status_code == 503
    assert "Confidential Space" in resp.json()["detail"]


def test_envelope_endpoint_signs_valid_intent():
    client = make_client()
    resp = client.post(
        "/envelope",
        json={"user": USER, "token_in": "USDC", "token_out": "WFLR", "amount_in": 100_000_000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["envelope"]["user"] == USER
    assert body["signature"].startswith("0x") and len(body["signature"]) == 132
    assert body["calldata"].startswith("0x")


def test_envelope_endpoint_refuses_overspend():
    client = make_client()
    resp = client.post(
        "/envelope",
        json={"user": USER, "token_in": "USDC", "token_out": "WFLR", "amount_in": 600_000_000},
    )
    assert resp.status_code == 403
    assert any("cap" in v for v in resp.json()["detail"]["violations"])


def test_envelope_endpoint_rejects_unknown_token():
    client = make_client()
    resp = client.post(
        "/envelope",
        json={"user": USER, "token_in": "DOGE", "token_out": "WFLR", "amount_in": 1},
    )
    assert resp.status_code == 400


def test_execute_calldata_round_trips():
    from web3 import Web3

    from ward_agent.chain import GUARDIAN_ABI

    client = make_client()
    signed = client.post(
        "/envelope",
        json={"user": USER, "token_in": "USDC", "token_out": "WFLR", "amount_in": 100_000_000},
    ).json()
    resp = client.post(
        "/execute-calldata",
        json={"envelope": signed["envelope"], "signature": signed["signature"], "calldata": signed["calldata"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["to"] == GUARDIAN

    contract = Web3().eth.contract(abi=GUARDIAN_ABI)
    fn, args = contract.decode_function_input(body["data"])
    assert fn.fn_name == "execute"
    assert args["amountIn"] == int(signed["envelope"]["maxAmountIn"])
    assert args["env"]["user"] == USER
    assert "0x" + args["data"].hex() == signed["calldata"]


def test_execute_calldata_rejects_malformed_envelope():
    client = make_client()
    resp = client.post(
        "/execute-calldata",
        json={"envelope": {"user": "0x0"}, "signature": "0x00", "calldata": "0x00"},
    )
    assert resp.status_code == 400
