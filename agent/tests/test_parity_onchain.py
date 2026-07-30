"""The test that matters: our Python EIP-712 digest must equal the deployed
Guardian's hashEnvelope() byte-for-byte, or no signature we produce will ever
verify on-chain."""

import pytest
from web3 import Web3

from tests.test_envelope import CHAIN_ID, GUARDIAN, SAMPLE
from ward_agent.chain import get_w3, guardian_contract
from ward_agent.config import get_settings


@pytest.fixture(scope="module")
def w3() -> Web3:
    w3 = get_w3(get_settings().rpc_url)
    if not w3.is_connected():
        pytest.skip("Coston2 RPC unreachable")
    return w3


def test_local_digest_matches_deployed_guardian(w3: Web3):
    guardian = guardian_contract(w3, GUARDIAN)
    onchain = guardian.functions.hashEnvelope(SAMPLE.as_tuple()).call()
    local = SAMPLE.signing_hash(CHAIN_ID, GUARDIAN)
    assert bytes(onchain) == local
