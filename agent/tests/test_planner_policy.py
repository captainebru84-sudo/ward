import pytest

from ward_agent.planner import Planner, SwapIntent, TokenInfo, build_envelope, fair_value_out
from ward_agent.policy import Policy, PolicyEngine

DEX = "0x00000000000000000000000000000000000d0d0d"
USER = "0xb7586261637550072E13B8D41bfA62345C55f635"

TOKENS = {
    "USDC": TokenInfo(address="0x1111111111111111111111111111111111111111", decimals=6),
    "WFLR": TokenInfo(address="0x2222222222222222222222222222222222222222", decimals=18),
}

# USDC/USD = 1.00 (value 100, decimals 2), FLR/USD = 0.00625 (value 625, decimals 5)
PRICES = {"stub": [(100, 2), (625, 5)]}


def stub_ftso_read(feed_ids):
    return PRICES["stub"]


@pytest.fixture
def planner() -> Planner:
    return Planner(tokens=TOKENS, dex_address=DEX, ftso_read=stub_ftso_read)


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine(
        {
            "default": Policy(
                max_spend={"USDC": 500_000_000},
                allowed_targets={DEX: ["swap(address,address,uint256)"]},
                max_slippage_bps=100,
                max_deadline_seconds=600,
            )
        }
    )


def test_fair_value_math():
    # 100 USDC at $1.00 into FLR at $0.00625 -> 16000 FLR
    fair = fair_value_out(100 * 10**6, (100, 2), (625, 5), 6, 18)
    assert fair == 16_000 * 10**18


def test_fair_value_negative_feed_decimals():
    # price 5000 with decimals -2 means 500000; symmetric scaling must cancel out
    a = fair_value_out(10**6, (100, 2), (5, -2), 6, 18)
    b = fair_value_out(10**6, (100, 2), (500, 0), 6, 18)
    assert a == b


def test_plan_swap_quotes_min_out(planner: Planner):
    plan = planner.plan_swap(
        SwapIntent(user=USER, token_in="USDC", token_out="WFLR", amount_in=100 * 10**6)
    )
    assert plan.fair_out == 16_000 * 10**18
    assert plan.min_out == plan.fair_out * 9_950 // 10_000  # default 50 bps
    assert plan.target == DEX
    assert plan.calldata().hex().startswith(plan.selector.hex())


def test_policy_passes_clean_plan(planner: Planner, engine: PolicyEngine):
    plan = planner.plan_swap(
        SwapIntent(user=USER, token_in="USDC", token_out="WFLR", amount_in=100 * 10**6)
    )
    assert engine.check(plan) == []


def test_policy_blocks_overspend(planner: Planner, engine: PolicyEngine):
    plan = planner.plan_swap(
        SwapIntent(user=USER, token_in="USDC", token_out="WFLR", amount_in=600 * 10**6)
    )
    assert any("cap" in v for v in engine.check(plan))


def test_policy_blocks_unknown_target(planner: Planner, engine: PolicyEngine):
    plan = planner.plan_swap(
        SwapIntent(user=USER, token_in="USDC", token_out="WFLR", amount_in=10**6)
    )
    plan = plan.model_copy(update={"target": "0x000000000000000000000000000000000000bEEF"})
    assert any("allowlist" in v for v in engine.check(plan))


def test_policy_blocks_forbidden_selector(planner: Planner, engine: PolicyEngine):
    plan = planner.plan_swap(
        SwapIntent(user=USER, token_in="USDC", token_out="WFLR", amount_in=10**6)
    )
    plan = plan.model_copy(update={"function_sig": "drainApproval(address,address)"})
    assert any("not allowed" in v for v in engine.check(plan))


def test_policy_blocks_excessive_slippage(planner: Planner, engine: PolicyEngine):
    plan = planner.plan_swap(
        SwapIntent(
            user=USER, token_in="USDC", token_out="WFLR", amount_in=10**6, max_slippage_bps=200
        )
    )
    assert any("slippage" in v for v in engine.check(plan))


def test_policy_blocks_long_deadline(planner: Planner, engine: PolicyEngine):
    plan = planner.plan_swap(
        SwapIntent(
            user=USER, token_in="USDC", token_out="WFLR", amount_in=10**6, ttl_seconds=3600
        )
    )
    assert any("ttl" in v for v in engine.check(plan))


def test_build_envelope_maps_plan(planner: Planner):
    plan = planner.plan_swap(
        SwapIntent(user=USER, token_in="USDC", token_out="WFLR", amount_in=100 * 10**6)
    )
    env = build_envelope(plan, now=1_800_000_000, nonce=7)
    assert env.user == USER
    assert env.maxAmountIn == plan.amount_in
    assert env.minOut == plan.min_out
    assert env.deadline == 1_800_000_000 + plan.ttl_seconds
    assert env.nonce == 7
    assert env.selector == plan.selector
