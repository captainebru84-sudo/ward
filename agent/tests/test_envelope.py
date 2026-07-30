from eth_account import Account
from eth_utils import function_signature_to_4byte_selector

from ward_agent import feeds
from ward_agent.envelope import SafetyEnvelope

CHAIN_ID = 114
GUARDIAN = "0x36A5153A84f6edaaB1ADb3AeF9F6C46ff5592b78"

SAMPLE = SafetyEnvelope(
    user="0xb7586261637550072E13B8D41bfA62345C55f635",
    target="0x000000000000000000000000000000000000dEaD",
    selector=function_signature_to_4byte_selector("swap(address,address,uint256)"),
    tokenIn="0x1111111111111111111111111111111111111111",
    maxAmountIn=100_000_000,
    tokenOut="0x2222222222222222222222222222222222222222",
    minOut=15_000 * 10**18,
    feedIn=feeds.USDC_USD,
    feedOut=feeds.FLR_USD,
    maxSlippageBps=50,
    deadline=1_800_000_000,
    nonce=42,
)


def test_signing_hash_is_deterministic():
    h1 = SAMPLE.signing_hash(CHAIN_ID, GUARDIAN)
    h2 = SAMPLE.signing_hash(CHAIN_ID, GUARDIAN)
    assert h1 == h2
    assert len(h1) == 32


def test_signature_recovers_to_signer():
    acct = Account.create()
    sig = SAMPLE.sign(acct.key, CHAIN_ID, GUARDIAN)
    recovered = Account.recover_message(SAMPLE.signable(CHAIN_ID, GUARDIAN), signature=sig)
    assert recovered == acct.address


def test_hash_changes_with_any_field():
    base = SAMPLE.signing_hash(CHAIN_ID, GUARDIAN)
    for change in (
        {"maxAmountIn": SAMPLE.maxAmountIn + 1},
        {"minOut": SAMPLE.minOut - 1},
        {"nonce": SAMPLE.nonce + 1},
        {"maxSlippageBps": 51},
        {"feedOut": feeds.BTC_USD},
    ):
        mutated = SAMPLE.model_copy(update=change)
        assert mutated.signing_hash(CHAIN_ID, GUARDIAN) != base


def test_feed_id_encoding():
    assert feeds.FLR_USD.hex() == "01464c522f55534400000000000000000000000000"
    assert len(feeds.USDC_USD) == 21
