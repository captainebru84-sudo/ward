import { ethers } from "hardhat";

// Trustless signer rotation: anyone — not the owner — can install the enclave's
// key on Guardian by relaying the Google-signed attestation token on-chain.
// WardAttestor verifies the RS256 signature and the pinned image digest itself.
//
// Env:
//   WARD_AGENT_URL  agent base URL to pull a fresh token from (default http://localhost:8080)
//   TOKEN           raw JWT — bypasses the fetch (e.g. replaying a captured token)
//   GUARDIAN        override Guardian address
//
// Run: WARD_AGENT_URL=http://<vm-ip>:8080 npx hardhat run scripts/ward/rotateByAttestation.ts --network coston2

const GUARDIAN = process.env.GUARDIAN ?? "0x5FCDc267ca392B64362957b7FD021719466d1775";

async function getToken(): Promise<string> {
    if (process.env.TOKEN) return process.env.TOKEN.trim();
    const base = process.env.WARD_AGENT_URL ?? "http://localhost:8080";
    const r = await fetch(`${base}/attestation`);
    if (!r.ok) throw new Error(`GET ${base}/attestation → ${r.status} (agent not in a TEE?)`);
    const { token, signer } = await r.json();
    console.log("Agent-reported signer:", signer);
    return token;
}

async function main() {
    const token = await getToken();
    const [headerB64, payloadB64, sigB64] = token.split(".");
    if (!sigB64) throw new Error("not a JWT: expected three dot-separated segments");
    const header = Buffer.from(headerB64, "base64url");
    const payload = Buffer.from(payloadB64, "base64url");
    const signature = Buffer.from(sigB64, "base64url");

    const claims = JSON.parse(payload.toString());
    const expected = ethers.getAddress(claims.eat_nonce);
    console.log("Attested image:   ", claims.submods?.container?.image_digest);
    console.log("hwmodel / swname: ", claims.hwmodel, "/", claims.swname);
    console.log("eat_nonce → signer:", expected);

    // fail fast instead of burning gas on a revert (token validity is ~1h)
    const now = Math.floor(Date.now() / 1000);
    if (now < claims.iat || now > claims.exp)
        throw new Error(`token outside validity window (iat ${claims.iat}, exp ${claims.exp}, now ${now})`);

    const signers = await ethers.getSigners();
    const submitter = signers[1] ?? signers[0];
    if (!signers[1]) console.warn("!! NONOWNER_KEY unset — submitting as owner, which weakens the trustless demo");

    const guardian = await ethers.getContractAt("Guardian", GUARDIAN, submitter);
    console.log("Guardian owner:   ", await guardian.owner());
    console.log("Submitter:        ", submitter.address, signers[1] ? "(not the owner — that's the point)" : "");
    console.log("wardSigner before:", await guardian.wardSigner());

    const tx = await guardian.rotateSignerByAttestation(header, payload, signature);
    const receipt = await tx.wait();
    console.log("rotateSignerByAttestation tx:", receipt?.hash);

    const after = await guardian.wardSigner();
    console.log("wardSigner after: ", after);
    if (after !== expected) throw new Error(`mismatch: expected ${expected}, got ${after}`);
    console.log("✓ enclave key installed via on-chain attestation — no owner involved");
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
