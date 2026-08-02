import { ethers } from "hardhat";

const GUARDIAN = "0x5FCDc267ca392B64362957b7FD021719466d1775";

async function main() {
    const newSigner = process.env.NEW_WARD_SIGNER;
    if (!newSigner) throw new Error("set NEW_WARD_SIGNER to the enclave signer address");

    const [owner] = await ethers.getSigners();
    const guardian = await ethers.getContractAt("Guardian", GUARDIAN);

    console.log("Owner:", owner.address);
    console.log("wardSigner before:", await guardian.wardSigner());

    const tx = await guardian.setWardSigner(newSigner);
    const receipt = await tx.wait();
    console.log("setWardSigner tx:", receipt?.hash);
    console.log("wardSigner after:", await guardian.wardSigner());
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
