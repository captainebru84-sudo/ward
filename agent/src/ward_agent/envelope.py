"""SafetyEnvelope: the EIP-712 message Guardian enforces on-chain.

Must stay byte-for-byte compatible with Guardian.sol's ENVELOPE_TYPEHASH and
_hashTypedDataV4 (domain "Ward Guardian" version "1"). The parity test in
tests/test_envelope.py checks our digest against the deployed contract's
hashEnvelope() view.
"""

from eth_account import Account
from eth_account.messages import SignableMessage, encode_typed_data
from eth_utils import keccak
from pydantic import BaseModel, field_validator

DOMAIN_NAME = "Ward Guardian"
DOMAIN_VERSION = "1"

ENVELOPE_TYPES = {
    "SafetyEnvelope": [
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
}


class SafetyEnvelope(BaseModel):
    user: str
    target: str
    selector: bytes  # 4 bytes
    tokenIn: str
    maxAmountIn: int
    tokenOut: str
    minOut: int
    feedIn: bytes  # 21 bytes
    feedOut: bytes  # 21 bytes
    maxSlippageBps: int
    deadline: int
    nonce: int

    @field_validator("selector")
    @classmethod
    def _selector_len(cls, v: bytes) -> bytes:
        if len(v) != 4:
            raise ValueError("selector must be 4 bytes")
        return v

    @field_validator("feedIn", "feedOut")
    @classmethod
    def _feed_len(cls, v: bytes) -> bytes:
        if len(v) != 21:
            raise ValueError("feed id must be 21 bytes")
        return v

    def domain(self, chain_id: int, guardian: str) -> dict:
        return {
            "name": DOMAIN_NAME,
            "version": DOMAIN_VERSION,
            "chainId": chain_id,
            "verifyingContract": guardian,
        }

    def signable(self, chain_id: int, guardian: str) -> SignableMessage:
        return encode_typed_data(
            domain_data=self.domain(chain_id, guardian),
            message_types=ENVELOPE_TYPES,
            message_data=self.model_dump(),
        )

    def signing_hash(self, chain_id: int, guardian: str) -> bytes:
        msg = self.signable(chain_id, guardian)
        return keccak(b"\x19\x01" + bytes(msg.header) + bytes(msg.body))

    def sign(self, private_key: str, chain_id: int, guardian: str) -> bytes:
        signed = Account.sign_message(self.signable(chain_id, guardian), private_key)
        return signed.signature

    def as_tuple(self) -> tuple:
        """Struct order expected by Guardian.execute / hashEnvelope."""
        return (
            self.user,
            self.target,
            self.selector,
            self.tokenIn,
            self.maxAmountIn,
            self.tokenOut,
            self.minOut,
            self.feedIn,
            self.feedOut,
            self.maxSlippageBps,
            self.deadline,
            self.nonce,
        )

    def as_json(self) -> dict:
        """Hex-encoded form for API responses / UI consumption."""
        d = self.model_dump()
        for k in ("selector", "feedIn", "feedOut"):
            d[k] = "0x" + d[k].hex()
        for k in ("maxAmountIn", "minOut", "maxSlippageBps", "deadline", "nonce"):
            d[k] = str(d[k])
        return d
