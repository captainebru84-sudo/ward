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
