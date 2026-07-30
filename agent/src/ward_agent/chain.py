"""Thin web3 helpers for Coston2 reads (FTSO quotes, Guardian views)."""

from web3 import Web3

FTSO_ABI = [
    {
        "name": "getFeedsById",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "ids", "type": "bytes21[]"}],
        "outputs": [
            {"name": "values", "type": "uint256[]"},
            {"name": "decimals", "type": "int8[]"},
            {"name": "timestamp", "type": "uint64"},
        ],
    }
]

GUARDIAN_ABI = [
    {
        "name": "hashEnvelope",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {
                "name": "env",
                "type": "tuple",
                "components": [
                    {"name": "user", "type": "address"},
                    {"name": "target", "type": "address"},
                    {"name": "selector", "type": "bytes4"},
                    {"name": "tokenIn", "type": "address"},
                    {"name": "maxAmountIn", "type": "uint256"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "minOut", "type": "uint256"},
                    {"name": "feedIn", "type": "bytes21"},
                    {"name": "feedOut", "type": "bytes21"},
                    {"name": "maxSlippageBps", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                ],
            }
        ],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    {
        "name": "wardSigner",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
]

FTSO_COSTON2 = "0xC4e9c78EA53db782E28f28Fdf80BaF59336B304d"


def get_w3(rpc_url: str) -> Web3:
    return Web3(Web3.HTTPProvider(rpc_url))


class FtsoReader:
    def __init__(self, w3: Web3, address: str = FTSO_COSTON2):
        self.contract = w3.eth.contract(Web3.to_checksum_address(address), abi=FTSO_ABI)

    def read(self, feed_ids: list[bytes]) -> list[tuple[int, int]]:
        """Returns [(value, decimals)] per feed, same order as feed_ids."""
        values, decimals, _ts = self.contract.functions.getFeedsById(feed_ids).call()
        return list(zip(values, decimals))


def guardian_contract(w3: Web3, address: str):
    return w3.eth.contract(Web3.to_checksum_address(address), abi=GUARDIAN_ABI)
