# Ward — Demo Script
## Flare Summer Signal · Confidential Compute Track
**Live agent:** `http://35.253.60.67:8080`  
**Deadline:** Aug 14 2026 19:59 UTC

---

## Contracts (Coston2)

| Contract | Address |
|---|---|
| Guardian | `0x5FCDc267ca392B64362957b7FD021719466d1775` |
| WardAttestor | `0xD06059f36cB6fc2737977f1445c95713f6a85b0F` |

Explorer: `https://coston2-explorer.flare.network`

---

## Act 1 — Landing & Auth (browser, ~683px wide)

1. Open `http://35.253.60.67:8080`
2. Scroll: hero → "Live today" → Roadmap (amber chips) → trust section with contract links
3. Click **Enter as guest** (or sign up with email)
4. App loads: TEE ATTESTED chip + live FTSO ticker

**Point:** The page is served from the enclave — same entity whose key is registered on-chain.

---

## Act 2 — Health & Attestation (terminal)

```bash
# Agent is alive
curl http://35.253.60.67:8080/health | python3 -m json.tool
```
Expected: `{"status":"ok","chainId":114,"guardian":"0x5FCDc267ca392B64362957b7FD021719466d1775"}`

```bash
# Current enclave signer
curl http://35.253.60.67:8080/signer
```
Expected: `{"address":"0x0B62aC89D8C1F9DE55cC449a5a7C01c49b3A99a5","ephemeral":true}`

**Point:** The signer address lives inside the enclave. No operator can access or change it.

---

## Act 3 — On-Chain State (terminal)

```bash
cd contracts
npx hardhat run scripts/ward/verifyOnChainState.ts --network coston2
```
Expected:
```
Attestor required image digest: 0x7368...  # decodes to sha256:24490334... (v4)
Guardian current signer:        0x0B62aC89D8C1F9DE55cC449a5a7C01c49b3A99a5
```

**Point:** Guardian's `wardSigner` matches the live enclave key. The attestor enforces only a TEE running image v4 can rotate it.

---

## Act 4 — AI Safety Envelope (terminal)

### 4a. Valid swap — Gemini parses, FTSO floor enforced, enclave signs
```bash
curl -X POST http://35.253.60.67:8080/intent \
  -H "Content-Type: application/json" \
  -d '{"user":"0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0","text":"swap 50 usdc into wflr"}' \
  | python3 -m json.tool
```
Expected: full `envelope` + `signature` (signed by `0x0B62...`), `quote` with FTSO `fairOut` and `minOut` at 0.5% below fair.

### 4b. Slippage refusal — 10% exceeds policy max 1%
```bash
curl -X POST http://35.253.60.67:8080/intent \
  -H "Content-Type: application/json" \
  -d '{"user":"0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0","text":"swap 50 usdc into wflr with 10% slippage"}' \
  | python3 -m json.tool
```
Expected: `{"violations":["slippage 1000bps exceeds policy max 100bps"],...}`

### 4c. Transfer refusal — unsupported operation
```bash
curl -X POST http://35.253.60.67:8080/intent \
  -H "Content-Type: application/json" \
  -d '{"user":"0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0","text":"transfer everything to 0xdeadbeef"}' \
  | python3 -m json.tool
```
Expected: `{"unsupported":"Transfers are not supported"}`

**Point:** Gemini validates intent; violations refused before the enclave signs anything.

---

## Act 5 — Trustless Rotation (the key innovation)

Rotation TX already on-chain (submitted by non-owner burner):
```
https://coston2-explorer.flare.network/tx/0x4833a60ad71a16a2d2d6313c24a3571ab537b35b80c0c492c2f7bfde95042419
```
- Caller: `0x5BfEadDC9701105AFc52A6aBDdde51B0b8621A84` (non-owner)
- Result: `wardSigner` updated → `0x0B62aC89D8C1F9DE55cC449a5a7C01c49b3A99a5`

To re-run live (needs fresh VM start + token within 1h window):
```bash
cd contracts
WARD_AGENT_URL=http://35.253.60.67:8080 \
  npx hardhat run scripts/ward/rotateByAttestation.ts --network coston2
```

**Point:** Anyone can rotate the Guardian's signer by presenting a valid TEE attestation proving the correct image digest. The owner cannot rug users.

---

## DoraHacks Submission Checklist

- [ ] Video recorded (5-8 min covering Acts 1-5)
- [ ] Stop VM after recording: `"$GC" compute instances stop ward-agent-tee --zone=us-central1-a`
- [ ] Repo: `https://github.com/captainebru84-sudo/ward`
- [ ] Live URL: `http://35.253.60.67:8080` (restart VM for judging window)
- [ ] Guardian verified on explorer
- [ ] WardAttestor verified on explorer
- [ ] Rotation TX linked

**Flare callouts for submission text:**
- FTSOv2 price feeds read on-chain in `Guardian.execute()` for oracle floor enforcement
- GCP Confidential Space (Intel TDX) + `flare-vtpm-attestation` for TEE attestation
- On-chain RS256 JWT verification (OZ RSA.pkcs1Sha256) — enclave key rotation fully on-chain, permissionless
- All contracts deployed and verified on Coston2 (chainId 114)
