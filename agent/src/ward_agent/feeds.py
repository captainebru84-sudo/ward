"""FTSO v2 feed IDs.

A feed ID is bytes21: one category byte (0x01 = crypto) followed by the
ASCII feed name, zero-padded. E.g. FLR/USD ->
0x01464c522f55534400000000000000000000000000.
"""

CATEGORY_CRYPTO = 0x01

ZERO_FEED = b"\x00" * 21


def feed_id(name: str, category: int = CATEGORY_CRYPTO) -> bytes:
    ascii_name = name.encode("ascii")
    if len(ascii_name) > 20:
        raise ValueError(f"feed name too long: {name}")
    return bytes([category]) + ascii_name.ljust(20, b"\x00")


FLR_USD = feed_id("FLR/USD")
BTC_USD = feed_id("BTC/USD")
ETH_USD = feed_id("ETH/USD")
USDC_USD = feed_id("USDC/USD")
USDT_USD = feed_id("USDT/USD")

BY_SYMBOL = {
    "FLR": FLR_USD,
    "C2FLR": FLR_USD,
    "WFLR": FLR_USD,
    "BTC": BTC_USD,
    "ETH": ETH_USD,
    "USDC": USDC_USD,
    "USDT": USDT_USD,
}
