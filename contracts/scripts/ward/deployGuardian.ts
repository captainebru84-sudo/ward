import { ethers } from "hardhat";

// The Flare ContractRegistry lives at the same address on every Flare network.
const FLARE_CONTRACT_REGISTRY = "0xaD67FE66660Fb8dFE9d6b1b4240d8650e30F6019";

async function main() {
    const [deployer] = await ethers.getSigners();
    const registry = new ethers.Contract(
        FLARE_CONTRACT_REGISTRY,
        ["function getContractAddressByName(string _name) view returns (address)"],
        ethers.provider
    );
    const ftsoV2 = await registry.getContractAddressByName("FtsoV2");
    const wardSigner = process.env.WARD_SIGNER ?? deployer.address;

    console.log("Deployer:", deployer.address);
    console.log("FtsoV2 (from ContractRegistry):", ftsoV2);
    console.log("Ward signer:", wardSigner);

    const guardian = await (await ethers.getContractFactory("Guardian")).deploy(wardSigner, ftsoV2);
    await guardian.waitForDeployment();
    console.log("Guardian deployed at:", await guardian.getAddress());
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
