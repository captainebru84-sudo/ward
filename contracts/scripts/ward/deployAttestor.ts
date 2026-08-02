import { ethers } from "hardhat";

// Deploys WardAttestor, registers Google's current Confidential Space signing
// keys, and wires the attestor into Guardian. From then on, ANYONE can rotate
// Guardian's ward signer by submitting a fresh attestation token.
//
// Env:
//   GUARDIAN      Guardian address to wire (required)
//   IMAGE_DIGEST  sha256:... digest of the attested agent image (required)

const JWKS_URI =
    "https://www.googleapis.com/service_accounts/v1/metadata/jwk/signer@confidentialspace-sign.iam.gserviceaccount.com";

const REQUIRED_CONFIG = {
    iss: "https://confidentialcomputing.googleapis.com",
    hwmodel: "GCP_INTEL_TDX",
    swname: "CONFIDENTIAL_SPACE",
    secboot: true,
};

function b64urlToHex(s: string): string {
    return "0x" + Buffer.from(s, "base64url").toString("hex");
}

async function main() {
    const guardianAddress = process.env.GUARDIAN;
    const imageDigest = process.env.IMAGE_DIGEST;
    if (!guardianAddress) throw new Error("set GUARDIAN to the Guardian address");
    if (!imageDigest?.startsWith("sha256:")) throw new Error("set IMAGE_DIGEST to sha256:...");

    const [deployer] = await ethers.getSigners();
    console.log("Deployer:", deployer.address);
    console.log("Required image digest:", imageDigest);

    const attestor = await (
        await ethers.getContractFactory("WardAttestor")
    ).deploy(
        REQUIRED_CONFIG.iss,
        REQUIRED_CONFIG.hwmodel,
        REQUIRED_CONFIG.swname,
        imageDigest,
        REQUIRED_CONFIG.secboot
    );
    await attestor.waitForDeployment();
    console.log("WardAttestor deployed at:", await attestor.getAddress());

    const jwks: { keys: { kid: string; e: string; n: string }[] } = await (await fetch(JWKS_URI)).json();
    for (const key of jwks.keys) {
        const tx = await attestor.addPubKey(
            ethers.toUtf8Bytes(key.kid),
            b64urlToHex(key.e),
            b64urlToHex(key.n)
        );
        await tx.wait();
        console.log("Registered Google key kid:", key.kid);
    }

    const guardian = await ethers.getContractAt("Guardian", guardianAddress);
    const tx = await guardian.setAttestor(await attestor.getAddress());
    await tx.wait();
    console.log("Guardian.attestor set:", await guardian.attestor());
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
