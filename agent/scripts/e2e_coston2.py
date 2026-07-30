"""First true E2E on Coston2: the agent quotes and signs a Safety Envelope,
the user executes it through Guardian against the live MockDEX, and a
tampered attempt is refused on-chain.

Run from agent/:  uv run python scripts/e2e_coston2.py
Requires .env with WARD_SIGNER_KEY (must be Guardian.wardSigner) and
WARD_DEX_ADDRESS. The same key doubles as the demo user.

TEE mode: set WARD_AGENT_URL=http://<tee-ip>:8080 and the envelope is
quoted and signed by the remote Confidential Space agent instead; the
local key is then only the demo user, not the signer.
"""

import base64
import json
import os
import urllib.request

from eth_account import Account
from eth_utils import function_signature_to_4byte_selector
from web3 import Web3
from web3.exceptions import ContractLogicError

from ward_agent.chain import ERC20_ABI, get_w3, guardian_contract
from ward_agent.config import get_settings
from ward_agent.planner import SwapIntent

AMOUNT_IN = 100 * 10**18  # 100 mock USDC


def http_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read())


def http_post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def print_attestation(agent_url: str) -> None:
    try:
        token = http_get(f"{agent_url}/attestation")["token"]
    except Exception as e:
        print(f"attestation unavailable ({e}) — agent not in a TEE?")
        return
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    container = claims.get("submods", {}).get("container", {})
    print("TEE attestation (signed by Google Confidential Computing):")
    print(f"  hwmodel:      {claims.get('hwmodel')}")
    print(f"  image_digest: {container.get('image_digest')}")
    print(f"  eat_nonce:    {claims.get('eat_nonce')}  <- enclave wardSigner")
    print(f"  dbgstat:      {claims.get('dbgstat')}")


def send(w3: Web3, account, tx) -> dict:
    tx.setdefault("nonce", w3.eth.get_transaction_count(account.address))
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1, f"tx failed: {tx_hash.hex()}"
    return receipt


def main() -> None:
    s = get_settings()
    agent_url = os.environ.get("WARD_AGENT_URL", "").rstrip("/")
    w3 = get_w3(s.rpc_url)
    user = Account.from_key(s.signer_key)
    guardian = guardian_contract(w3, s.guardian_address)

    if agent_url:
        print(f"TEE mode: envelopes signed by remote agent at {agent_url}")
        signer_info = http_get(f"{agent_url}/signer")
        agent_signer = signer_info["address"]
        print(f"remote signer: {agent_signer} (ephemeral={signer_info['ephemeral']})")
        print_attestation(agent_url)
    else:
        from ward_agent.api import build_service

        service = build_service(s)
        agent_signer = service.signer.address

    onchain_signer = guardian.functions.wardSigner().call()
    assert onchain_signer == agent_signer, (
        f"agent signer {agent_signer} != Guardian.wardSigner {onchain_signer}"
    )
    print(f"wardSigner OK: {onchain_signer}")

    if agent_url:
        result = http_post(
            f"{agent_url}/envelope",
            {
                "user": user.address,
                "token_in": "USDC",
                "token_out": "WFLR",
                "amount_in": AMOUNT_IN,
            },
        )
    else:
        intent = SwapIntent(
            user=user.address, token_in="USDC", token_out="WFLR", amount_in=AMOUNT_IN
        )
        result = service.handle_swap(intent)
    print(f"quote: {result['quote']}")

    env = result["envelope"]
    env_tuple = (
        env["user"],
        env["target"],
        bytes.fromhex(env["selector"][2:]),
        env["tokenIn"],
        int(env["maxAmountIn"]),
        env["tokenOut"],
        int(env["minOut"]),
        bytes.fromhex(env["feedIn"][2:]),
        bytes.fromhex(env["feedOut"][2:]),
        int(env["maxSlippageBps"]),
        int(env["deadline"]),
        int(env["nonce"]),
    )
    sig = bytes.fromhex(result["signature"][2:])
    calldata = bytes.fromhex(result["calldata"][2:])

    usdc = w3.eth.contract(Web3.to_checksum_address(env["tokenIn"]), abi=ERC20_ABI)
    wflr = w3.eth.contract(Web3.to_checksum_address(env["tokenOut"]), abi=ERC20_ABI)

    print("approving Guardian for 100 USDC...")
    send(w3, user, usdc.functions.approve(s.guardian_address, AMOUNT_IN).build_transaction(
        {"from": user.address}
    ))

    wflr_before = wflr.functions.balanceOf(user.address).call()
    print("executing envelope through Guardian...")
    receipt = send(w3, user, guardian.functions.execute(
        env_tuple, sig, AMOUNT_IN, calldata
    ).build_transaction({"from": user.address}))
    wflr_after = wflr.functions.balanceOf(user.address).call()

    received = wflr_after - wflr_before
    print(f"EXECUTED in block {receipt['blockNumber']}, tx {receipt['transactionHash'].hex()}")
    print(f"received {received / 10**18:.4f} WFLR (minOut was {int(env['minOut']) / 10**18:.4f})")
    assert received >= int(env["minOut"])

    # Tamper attempt: same signed envelope, calldata swapped for drainApproval.
    evil = function_signature_to_4byte_selector("drainApproval(address,address)") + calldata[4:]
    print("attempting tampered calldata (drainApproval)...")
    try:
        guardian.functions.execute(env_tuple, sig, AMOUNT_IN, evil).call({"from": user.address})
        raise SystemExit("GUARDIAN FAILED TO BLOCK THE TAMPERED CALL")
    except ContractLogicError as e:
        print(f"refused on-chain as expected: {e.message or e}")

    print("E2E PASSED")


if __name__ == "__main__":
    main()
