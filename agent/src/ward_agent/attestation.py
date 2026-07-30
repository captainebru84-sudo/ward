"""Confidential Space attestation.

Inside a Confidential Space VM the container launcher exposes a token service
on a unix socket. We request an OIDC attestation token with the wardSigner
address embedded as an EAT nonce: the token then proves that this exact
hardware-attested image is the one holding that signing key.
"""

import http.client
import json
import socket
from pathlib import Path

TEE_SOCKET = "/run/container_launcher/teeserver.sock"
DEFAULT_AUDIENCE = "ward-guardian"


class NotInTee(Exception):
    pass


class _UnixSocketConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self._socket_path)
        self.sock = sock


def fetch_attestation_token(signer_address: str, audience: str = DEFAULT_AUDIENCE) -> str:
    if not Path(TEE_SOCKET).exists():
        raise NotInTee(f"{TEE_SOCKET} not present — not running in Confidential Space")
    body = json.dumps({"audience": audience, "token_type": "OIDC", "nonces": [signer_address]})
    conn = _UnixSocketConnection(TEE_SOCKET)
    try:
        conn.request("POST", "/v1/token", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read().decode()
        if resp.status != 200:
            raise RuntimeError(f"attestation token request failed: {resp.status} {data}")
        return data
    finally:
        conn.close()
