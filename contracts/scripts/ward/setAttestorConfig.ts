import { ethers } from "hardhat";

// Updates WardAttestor's required config to pin a new agent image digest.
//
// Env:
//   ATTESTOR_ADDRESS  WardAttestor contract address (required)
//   IMAGE_DIGEST      sha256:... digest of the new agent image (required)

const REQUIRED_CONFIG = {
    iss: "https://confidentialcomputing.googleapis.com",
    hwmodel: "GCP_INTEL_TDX",
    swname: "CONFIDENTIAL_SPACE",
    secboot: true,
};

async function main() {
    const attestorAddress = process.env.ATTESTOR_ADDRESS;
    const imageDigest = process.env.IMAGE_DIGEST;
    if (!attestorAddress) throw new Error("set ATTESTOR_ADDRESS");
    if (!imageDigest?.startsWith("sha256:")) throw new Error("set IMAGE_DIGEST to sha256:...");

    const [deployer] = await ethers.getSigners();
    console.log("Caller:", deployer.address);
    console.log("Attestor:", attestorAddress);
    console.log("New image digest:", imageDigest);

    const attestor = await ethers.getContractAt("WardAttestor", attestorAddress);
    const tx = await attestor.setRequiredConfig(
        REQUIRED_CONFIG.iss,
        REQUIRED_CONFIG.hwmodel,
        REQUIRED_CONFIG.swname,
        imageDigest,
        REQUIRED_CONFIG.secboot
    );
    await tx.wait();
    console.log("✓ attestor.setRequiredConfig() done, tx:", tx.hash);
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
