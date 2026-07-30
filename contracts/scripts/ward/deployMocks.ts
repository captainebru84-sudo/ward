import { ethers } from "hardhat";

// bytes21 FTSO feed id: 0x01 (crypto category) + ascii name, zero-padded right
const feedId = (name: string) =>
    "0x01" + Buffer.from(name, "ascii").toString("hex").padEnd(40, "0");

const FLARE_CONTRACT_REGISTRY = "0xaD67FE66660Fb8dFE9d6b1b4240d8650e30F6019";

async function main() {
    const [deployer] = await ethers.getSigners();
    console.log("Deployer:", deployer.address);

    const registry = new ethers.Contract(
        FLARE_CONTRACT_REGISTRY,
        ["function getContractAddressByName(string _name) view returns (address)"],
        ethers.provider
    );
    const ftsoV2 = new ethers.Contract(
        await registry.getContractAddressByName("FtsoV2"),
        [
            "function getFeedsById(bytes21[] _feedIds) view returns (uint256[] _values, int8[] _decimals, uint64 _timestamp)",
        ],
        ethers.provider
    );

    const usdc = await (await ethers.getContractFactory("MockERC20")).deploy("Ward Mock USDC", "USDC");
    await usdc.waitForDeployment();
    const wflr = await (await ethers.getContractFactory("MockERC20")).deploy("Ward Mock WFLR", "WFLR");
    await wflr.waitForDeployment();

    // Set the DEX rate to the live FTSO fair value so honest swaps clear the
    // Guardian's oracle floor. Both mock tokens are 18 decimals.
    // MockDEX: out = in * rate / 1e18   =>   rate = 1e18 * pIn * 10^dOut / (pOut * 10^dIn)
    const [values, decimals] = await ftsoV2.getFeedsById([feedId("USDC/USD"), feedId("FLR/USD")]);
    const [pIn, pOut] = [values[0] as bigint, values[1] as bigint];
    const [dIn, dOut] = [BigInt(decimals[0]), BigInt(decimals[1])];
    if (pIn === 0n || pOut === 0n) throw new Error("FTSO feed missing");
    const rate = (10n ** 18n * pIn * 10n ** dOut) / (pOut * 10n ** dIn);
    console.log("FTSO USDC/USD:", pIn.toString(), "dec", dIn.toString());
    console.log("FTSO FLR/USD:", pOut.toString(), "dec", dOut.toString());
    console.log("DEX rate (WFLR per USDC, 1e18):", rate.toString());

    const dex = await (await ethers.getContractFactory("MockDEX")).deploy(rate);
    await dex.waitForDeployment();

    const mintTx = await usdc.mint(deployer.address, ethers.parseUnits("1000000", 18));
    await mintTx.wait();

    console.log("USDC (18d):", await usdc.getAddress());
    console.log("WFLR (18d):", await wflr.getAddress());
    console.log("MockDEX:", await dex.getAddress());
    console.log("Minted 1,000,000 USDC to", deployer.address);
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
