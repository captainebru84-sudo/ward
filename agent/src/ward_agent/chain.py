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

ENVELOPE_COMPONENTS = [
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
]

GUARDIAN_ABI = [
    {
        "name": "hashEnvelope",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "env", "type": "tuple", "components": ENVELOPE_COMPONENTS}],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    {
        "name": "wardSigner",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "name": "execute",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {"name": "env", "type": "tuple", "components": ENVELOPE_COMPONENTS},
            {"name": "wardSig", "type": "bytes"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "data", "type": "bytes"},
        ],
        "outputs": [{"name": "amountOut", "type": "uint256"}],
    },
]

ERC20_ABI = [
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
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


def encode_execute(envelope: dict, signature: str, amount_in: int, calldata: str) -> str:
    """ABI-encodes Guardian.execute for the envelope's hex/string JSON form."""
    env_tuple = tuple(
        bytes.fromhex(envelope[c["name"]][2:])
        if c["type"].startswith("bytes")
        else Web3.to_checksum_address(envelope[c["name"]])
        if c["type"] == "address"
        else int(envelope[c["name"]])
        for c in ENVELOPE_COMPONENTS
    )
    contract = Web3().eth.contract(abi=GUARDIAN_ABI)
    return contract.encode_abi(
        "execute",
        args=[env_tuple, bytes.fromhex(signature[2:]), amount_in, bytes.fromhex(calldata[2:])],
    )
