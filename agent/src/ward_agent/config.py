from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

GUARDIAN_COSTON2 = "0x36A5153A84f6edaaB1ADb3AeF9F6C46ff5592b78"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WARD_", env_file=".env", extra="ignore")

    rpc_url: str = "https://coston2-api.flare.network/ext/C/rpc"
    chain_id: int = 114
    guardian_address: str = GUARDIAN_COSTON2
    dex_address: str = "0x0000000000000000000000000000000000000000"  # MockDEX, set after deploy
    signer_key: str = ""  # hex private key; empty = generate ephemeral (TEE mode)
    policies_path: str = "policies.json"
    tokens_path: str = "tokens.json"
    envelope_ttl_seconds: int = 300

    # NL intent layer. Either an API key (local dev) or Vertex mode (TEE: the
    # enclave's service account authenticates — no key inside the attested image).
    gemini_api_key: str = ""
    gemini_vertex: bool = False
    gemini_model: str = "gemini-2.5-flash"
    gcp_project: str = "ward-guardian-2026"
    gcp_location: str = "us-central1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
