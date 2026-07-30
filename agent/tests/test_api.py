from fastapi.testclient import TestClient

from tests.test_planner_policy import DEX, TOKENS, USER, stub_ftso_read
from ward_agent.api import AgentService, create_app
from ward_agent.planner import Planner
from ward_agent.policy import Policy, PolicyEngine
from ward_agent.signer import WardSigner

GUARDIAN = "0x36A5153A84f6edaaB1ADb3AeF9F6C46ff5592b78"


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
