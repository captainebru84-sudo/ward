import { ethers } from "hardhat";

// Re-pin the MockDEX fill rate to the live FTSO fair value. The Guardian's
// oracle floor moves with FTSO in real time, so a rate set at deploy drifts
// out of tolerance within hours — exactly the failure Guardian exists to catch.

const MOCK_DEX = "0xe1570af51Bfc33CDaEAD58378eE15416b370279e";
const FLARE_CONTRACT_REGISTRY = "0xaD67FE66660Fb8dFE9d6b1b4240d8650e30F6019";

const feedId = (name: string) =>
    "0x01" + Buffer.from(name, "ascii").toString("hex").padEnd(40, "0");

async function main() {
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

    const [values, decimals] = await ftsoV2.getFeedsById([feedId("USDC/USD"), feedId("FLR/USD")]);
    const [pIn, pOut] = [values[0] as bigint, values[1] as bigint];
    const [dIn, dOut] = [BigInt(decimals[0]), BigInt(decimals[1])];
    if (pIn === 0n || pOut === 0n) throw new Error("FTSO feed missing");
    const rate = (10n ** 18n * pIn * 10n ** dOut) / (pOut * 10n ** dIn);

    const dex = await ethers.getContractAt("MockDEX", MOCK_DEX);
    console.log("rate before:", (await dex.rate()).toString());
    const tx = await dex.setRate(rate);
    await tx.wait();
    console.log("rate after: ", (await dex.rate()).toString(), `(tx ${tx.hash})`);
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
