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
| **Guardian** | [`0x36A5153A84f6edaaB1ADb3AeF9F6C46ff5592b78`](https://coston2-explorer.flare.network/address/0x36A5153A84f6edaaB1ADb3AeF9F6C46ff5592b78) |
| FtsoV2 (resolved via ContractRegistry) | `0xC4e9c78EA53db782E28f28Fdf80BaF59336B304d` |

Guardian reads live FTSO v2 feeds on-chain to enforce fair-value bounds at execution time.

### TEE deployment (GCP Confidential Space, Intel TDX)

The policy agent runs in a **production** (non-debuggable) Confidential Space VM:

| | |
|---|---|
| Image | `us-central1-docker.pkg.dev/ward-guardian-2026/ward/agent@sha256:e34fa4ec04db97b6e3de440aeb01d65ea94237f9bde4281ab72207bc8f1e834a` |
| VM | `ward-agent-tee` (c3-standard-4, Intel TDX, us-central1-a), secure boot, `dbgstat: disabled-since-boot` |
| Enclave wardSigner | `0xeAaA74067F0c46204fB5fDd6531eb42d91a7821C` — generated at boot **inside** the enclave; no human ever saw this key |
| Signer rotation | [`0x6516357805bbb56101cc749917258ced60c17d1dd8b6ecacb79a292843a1cba7`](https://coston2-explorer.flare.network/tx/0x6516357805bbb56101cc749917258ced60c17d1dd8b6ecacb79a292843a1cba7) — owner pointed Guardian at the enclave key |
| TEE-signed E2E | [`0xe3e6324ead8a74bf71d153331736ff776371c75eb4fa6c98f434bcd52369035f`](https://coston2-explorer.flare.network/tx/0xe3e6324ead8a74bf71d153331736ff776371c75eb4fa6c98f434bcd52369035f) — envelope signed in the enclave, executed through Guardian; tampered calldata refused |

The agent's `GET /attestation` endpoint returns an OIDC token signed by Google Confidential Computing (`iss: https://confidentialcomputing.googleapis.com`) whose claims bind the running **image digest** (above), the hardware (`hwmodel: GCP_INTEL_TDX`), and the **enclave signer address** (as `eat_nonce`) into one verifiable statement: *this exact code, on this hardware, holds the only key Guardian trusts.* A captured sample lives in [`agent/attestation_sample.json`](agent/attestation_sample.json).

Bonus: during testing the Guardian's FTSO floor check refused a fill all by itself — the mock DEX's rate had been pinned a day earlier and FTSO's live fair value had drifted past the slippage tolerance. Exactly the failure mode Ward exists to catch.
