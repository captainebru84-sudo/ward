# Ward

**The DeFi copilot that puts its promises on-chain — and runs where no one can tamper with it.**

Ward is an AI transaction copilot for the [Flare Network](https://flare.network). It turns user intent into a transaction plan, checks it against the user's private safety policies inside a Trusted Execution Environment (TEE), and signs a **Safety Envelope** — hard guarantees (min output, allowed protocols, max slippage, deadline) that the on-chain **Guardian** contract enforces at execution time. If reality violates any guarantee, the transaction reverts.

> Every other AI DeFi copilot is an off-chain narrator: it explains the swap, you still confirm blind.
> Ward's promises are enforced by the chain, and the code that makes them is hardware-attested.

## How it uses Flare

| Flare feature | Role in Ward |
|---|---|
| **Confidential Compute / TEE** (GCP Confidential Space, Intel TDX) | The policy agent runs in an enclave. Your spending limits and allowlists never leave it; the enclave's code hash is attested on-chain. |
| **FTSO v2** | Guardian checks slippage / minOut bounds against Flare's enshrined ~1.8s oracle feeds at execution time. |
| **Coston2 testnet** | Current deployment target (chain ID 114). |

## Natural-language intents ("model proposes, policy engine disposes")

`POST /intent` takes free text — *"swap 100 usdc into wflr"* — and hands it to Gemini for **parsing only**. The model outputs a structured draft (tokens, amount, slippage); it never sees keys, addresses, prices, or policies, and its output still walks the same deterministic planner → policy → signer path as any structured request. A parsed intent that violates policy is refused with the exact rule it broke. Inside the TEE, Gemini is reached via **Vertex AI using the enclave's service account** — no API key exists inside the attested image.

## Repo layout

```
contracts/   Guardian contract + deployment (Hardhat, based on flare-hardhat-starter)
agent/       Ward policy agent (Python) — intent → plan → policy check → signed Safety Envelope
ui/          Chat + transaction review card (web)
```

## Status

Built during [Flare Summer Signal](https://dorahacks.io/hackathon/flaresummersignal) (July–August 2026). Work in progress.

### Deployment (Coston2, chain ID 114)

| Contract | Address |
|---|---|
| **Guardian** | [`0x5FCDc267ca392B64362957b7FD021719466d1775`](https://coston2-explorer.flare.network/address/0x5FCDc267ca392B64362957b7FD021719466d1775) |
| **WardAttestor** | [`0xD06059f36cB6fc2737977f1445c95713f6a85b0F`](https://coston2-explorer.flare.network/address/0xD06059f36cB6fc2737977f1445c95713f6a85b0F) |
| FtsoV2 (resolved via ContractRegistry) | `0xC4e9c78EA53db782E28f28Fdf80BaF59336B304d` |

Guardian reads live FTSO v2 feeds on-chain to enforce fair-value bounds at execution time.

### On-chain attestation → trustless signer rotation

`WardAttestor` (vendored and trimmed from [flare-vtpm-attestation](https://github.com/flare-foundation/flare-vtpm-attestation), MIT) verifies Google Confidential Space attestation tokens **entirely on-chain**: RS256 signature against Google's registered JWKS keys, then claims against the required config — issuer, `hwmodel: GCP_INTEL_TDX`, `swname: CONFIDENTIAL_SPACE`, secure boot, and the **exact container image digest**.

One deliberate change from the reference implementation: the reference binds an attestation to `msg.sender`, but JWTs are public calldata — anyone can replay one and register someone else's quote as their own. Ward instead binds to the token's **`eat_nonce` claim**: the enclave requests its own ephemeral signer address as the attestation nonce, so the address lives *inside* the Google-signed payload. That makes `Guardian.rotateSignerByAttestation` permissionless — **anyone** may submit a fresh token, replays are harmless (they resolve to the same attested key), and after every enclave restart the new key can be installed without trusting the owner or any operator. The attestor's tests verify the real captured token from `agent/attestation_sample.json` against Google's actual signing key.

### TEE deployment (GCP Confidential Space, Intel TDX)

The policy agent runs in a **production** (non-debuggable) Confidential Space VM:

| | |
|---|---|
| Image | `us-central1-docker.pkg.dev/ward-guardian-2026/ward/agent@sha256:a1626f0832edc918d69472201f65c65df9d4a5e29c1041fc79ac6dc005b78f27` |
| VM | `ward-agent-tee` (c3-standard-4, Intel TDX, us-central1-a), secure boot, `dbgstat: disabled-since-boot` |
| Enclave wardSigner | generated at boot **inside** the enclave; no human ever sees this key. Installed on-chain via `rotateSignerByAttestation` |
| TEE-signed E2E | [`0xe3e6324ead8a74bf71d153331736ff776371c75eb4fa6c98f434bcd52369035f`](https://coston2-explorer.flare.network/tx/0xe3e6324ead8a74bf71d153331736ff776371c75eb4fa6c98f434bcd52369035f) — envelope signed in the enclave (signer `0xeAaA…821C`), executed through Guardian on the initial deployment; tampered calldata refused |

The agent's `GET /attestation` endpoint returns an OIDC token signed by Google Confidential Computing (`iss: https://confidentialcomputing.googleapis.com`) whose claims bind the running **image digest** (above), the hardware (`hwmodel: GCP_INTEL_TDX`), and the **enclave signer address** (as `eat_nonce`) into one verifiable statement: *this exact code, on this hardware, holds the only key Guardian trusts.* A captured sample lives in [`agent/attestation_sample.json`](agent/attestation_sample.json).

Bonus: during testing the Guardian's FTSO floor check refused a fill all by itself — the mock DEX's rate had been pinned a day earlier and FTSO's live fair value had drifted past the slippage tolerance. Exactly the failure mode Ward exists to catch.
