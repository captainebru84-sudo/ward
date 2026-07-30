"""wardSigner key management.

Dev mode: key supplied via WARD_SIGNER_KEY. TEE mode: no key supplied — one is
generated at boot and never leaves the enclave; the owner then points Guardian
at it with setWardSigner(address).
"""

from eth_account import Account
from eth_account.signers.local import LocalAccount

from ward_agent.envelope import SafetyEnvelope


class WardSigner:
    def __init__(self, account: LocalAccount, ephemeral: bool):
        self._account = account
        self.ephemeral = ephemeral

    @classmethod
    def from_key_or_ephemeral(cls, private_key: str = "") -> "WardSigner":
        if private_key:
            return cls(Account.from_key(private_key), ephemeral=False)
        return cls(Account.create(), ephemeral=True)

    @property
    def address(self) -> str:
        return self._account.address

    def sign_envelope(self, env: SafetyEnvelope, chain_id: int, guardian: str) -> bytes:
        signed = self._account.sign_message(env.signable(chain_id, guardian))
        return signed.signature
