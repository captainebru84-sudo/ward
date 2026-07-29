import { loadFixture, time } from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { expect } from "chai";
import { ethers } from "hardhat";

const RATE = ethers.parseEther("2"); // 1 IN -> 2 OUT

// bytes21 FTSO feed IDs: 0x01 (category "crypto") + name, zero-padded
const FEED_USDC = "0x01555344432f555344000000000000000000000000"; // "USDC/USD"
const FEED_FLR = "0x01464c522f55534400000000000000000000000000"; // "FLR/USD"

async function deployFixture() {
    const [owner, user, attacker] = await ethers.getSigners();
    // In production this key lives inside the TEE; here it's a plain test signer.
    const wardAgent = ethers.Wallet.createRandom().connect(ethers.provider);

    const tokenIn = await (await ethers.getContractFactory("MockERC20")).deploy("USDCoin", "USDC");
    const tokenOut = await (await ethers.getContractFactory("MockERC20")).deploy("Wrapped FLR", "WFLR");
    const dex = await (await ethers.getContractFactory("MockDEX")).deploy(RATE);

    // Oracle agrees with the DEX rate: USDC = $1.00, FLR = $0.50 -> fair 1 USDC = 2 FLR
    const ftso = await (await ethers.getContractFactory("MockFtsoV2")).deploy();
    await ftso.setFeed(FEED_USDC, 10_000_000n, 7);
    await ftso.setFeed(FEED_FLR, 5_000_000n, 7);

    const guardian = await (
        await ethers.getContractFactory("Guardian")
    ).deploy(wardAgent.address, await ftso.getAddress());

    await tokenIn.mint(user.address, ethers.parseEther("1000"));
    await tokenIn.connect(user).approve(await guardian.getAddress(), ethers.MaxUint256);

    const domain = {
        name: "Ward Guardian",
        version: "1",
        chainId: (await ethers.provider.getNetwork()).chainId,
        verifyingContract: await guardian.getAddress(),
    };
    const types = {
        SafetyEnvelope: [
            { name: "user", type: "address" },
            { name: "target", type: "address" },
            { name: "selector", type: "bytes4" },
            { name: "tokenIn", type: "address" },
            { name: "maxAmountIn", type: "uint256" },
            { name: "tokenOut", type: "address" },
            { name: "minOut", type: "uint256" },
            { name: "feedIn", type: "bytes21" },
            { name: "feedOut", type: "bytes21" },
            { name: "maxSlippageBps", type: "uint256" },
            { name: "deadline", type: "uint256" },
            { name: "nonce", type: "uint256" },
        ],
    };

    const swapSelector = dex.interface.getFunction("swap")!.selector;

    async function makeEnvelope(overrides: Partial<Record<string, unknown>> = {}) {
        const envelope = {
            user: user.address,
            target: await dex.getAddress(),
            selector: swapSelector,
            tokenIn: await tokenIn.getAddress(),
            maxAmountIn: ethers.parseEther("100"),
            tokenOut: await tokenOut.getAddress(),
            minOut: ethers.parseEther("190"), // expects ~200 out for 100 in, 5% guard
            feedIn: FEED_USDC,
            feedOut: FEED_FLR,
            maxSlippageBps: 100n, // 1% vs FTSO fair value at execution time
            deadline: (await time.latest()) + 3600,
            nonce: 1n,
            ...overrides,
        };
        const signature = await wardAgent.signTypedData(domain, types, envelope);
        return { envelope, signature };
    }

    function swapData(amountIn: bigint) {
        return dex.interface.encodeFunctionData("swap", [
            tokenIn.target,
            tokenOut.target,
            amountIn,
        ]);
    }

    return { owner, user, attacker, wardAgent, tokenIn, tokenOut, dex, ftso, guardian, makeEnvelope, swapData };
}

describe("Guardian", () => {
    it("executes a swap that honors every envelope guarantee", async () => {
        const { user, guardian, tokenOut, makeEnvelope, swapData } = await loadFixture(deployFixture);
        const { envelope, signature } = await makeEnvelope();
        const amountIn = ethers.parseEther("100");

        await expect(guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn)))
            .to.emit(guardian, "EnvelopeExecuted");
        expect(await tokenOut.balanceOf(user.address)).to.equal(ethers.parseEther("200"));
    });

    it("reverts when output falls below minOut (sandwich / price move)", async () => {
        const { user, guardian, dex, makeEnvelope, swapData } = await loadFixture(deployFixture);
        const { envelope, signature } = await makeEnvelope();
        // price collapses between signing and execution
        await dex.setRate(ethers.parseEther("1.5"));
        const amountIn = ethers.parseEther("100");

        await expect(
            guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn))
        ).to.be.revertedWithCustomError(guardian, "InsufficientOutput");
    });

    it("reverts when the envelope has expired", async () => {
        const { user, guardian, makeEnvelope, swapData } = await loadFixture(deployFixture);
        const { envelope, signature } = await makeEnvelope();
        await time.increase(7200);
        const amountIn = ethers.parseEther("100");

        await expect(
            guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn))
        ).to.be.revertedWithCustomError(guardian, "EnvelopeExpired");
    });

    it("blocks calldata aimed at a function the envelope never approved", async () => {
        const { user, guardian, dex, tokenIn, makeEnvelope } = await loadFixture(deployFixture);
        const { envelope, signature } = await makeEnvelope();
        const malicious = dex.interface.encodeFunctionData("drainApproval", [
            tokenIn.target,
            user.address,
        ]);

        await expect(
            guardian.connect(user).execute(envelope, signature, ethers.parseEther("100"), malicious)
        ).to.be.revertedWithCustomError(guardian, "SelectorNotAllowed");
    });

    it("reverts when spend exceeds the envelope cap", async () => {
        const { user, guardian, makeEnvelope, swapData } = await loadFixture(deployFixture);
        const { envelope, signature } = await makeEnvelope();
        const amountIn = ethers.parseEther("500");

        await expect(
            guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn))
        ).to.be.revertedWithCustomError(guardian, "ExceedsMaxSpend");
    });

    it("refuses to execute the same envelope twice", async () => {
        const { user, guardian, makeEnvelope, swapData } = await loadFixture(deployFixture);
        const { envelope, signature } = await makeEnvelope();
        const amountIn = ethers.parseEther("100");

        await guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn));
        await expect(
            guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn))
        ).to.be.revertedWithCustomError(guardian, "EnvelopeAlreadyUsed");
    });

    it("rejects an envelope tampered with after signing", async () => {
        const { user, guardian, makeEnvelope, swapData } = await loadFixture(deployFixture);
        const { envelope, signature } = await makeEnvelope();
        const tampered = { ...envelope, minOut: 0n }; // attacker strips the guarantee
        const amountIn = ethers.parseEther("100");

        await expect(
            guardian.connect(user).execute(tampered, signature, amountIn, swapData(amountIn))
        ).to.be.revertedWithCustomError(guardian, "InvalidWardSignature");
    });

    it("rejects execution by anyone other than the envelope's user", async () => {
        const { attacker, guardian, makeEnvelope, swapData } = await loadFixture(deployFixture);
        const { envelope, signature } = await makeEnvelope();
        const amountIn = ethers.parseEther("100");

        await expect(
            guardian.connect(attacker).execute(envelope, signature, amountIn, swapData(amountIn))
        ).to.be.revertedWithCustomError(guardian, "NotEnvelopeUser");
    });

    it("reverts when the fill is below FTSO fair value, even though minOut passes", async () => {
        const { user, guardian, dex, makeEnvelope, swapData } = await loadFixture(deployFixture);
        // agent signed a lenient minOut (150), but capped oracle slippage at 1%
        const { envelope, signature } = await makeEnvelope({ minOut: ethers.parseEther("150") });
        // DEX fills 5% worse than the oracle's fair rate of 2.0
        await dex.setRate(ethers.parseEther("1.9"));
        const amountIn = ethers.parseEther("100");

        // 190 out clears minOut=150, but FTSO says fair is 200 -> floor 198
        await expect(
            guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn))
        ).to.be.revertedWithCustomError(guardian, "OracleSlippageExceeded");
    });

    it("tracks the live FTSO price: a fill fair at execution time passes", async () => {
        const { user, guardian, dex, ftso, makeEnvelope, swapData } = await loadFixture(deployFixture);
        // FLR pumps to $1.00 after signing -> fair is now 1:1, DEX follows
        const { envelope, signature } = await makeEnvelope({ minOut: ethers.parseEther("99") });
        await ftso.setFeed(FEED_FLR, 10_000_000n, 7);
        await dex.setRate(ethers.parseEther("1"));
        const amountIn = ethers.parseEther("100");

        await expect(guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn)))
            .to.emit(guardian, "EnvelopeExecuted");
    });

    it("skips the oracle check when maxSlippageBps is 0", async () => {
        const { user, guardian, dex, makeEnvelope, swapData } = await loadFixture(deployFixture);
        const { envelope, signature } = await makeEnvelope({
            minOut: ethers.parseEther("150"),
            maxSlippageBps: 0n,
        });
        await dex.setRate(ethers.parseEther("1.9"));
        const amountIn = ethers.parseEther("100");

        await expect(guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn)))
            .to.emit(guardian, "EnvelopeExecuted");
    });

    it("normalizes differing feed decimals correctly", async () => {
        const { user, guardian, ftso, makeEnvelope, swapData } = await loadFixture(deployFixture);
        // same real prices ($1.00, $0.50) expressed at different feed precisions
        await ftso.setFeed(FEED_USDC, 100n, 2);
        await ftso.setFeed(FEED_FLR, 50_000n, 5);
        const { envelope, signature } = await makeEnvelope();
        const amountIn = ethers.parseEther("100");

        await expect(guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn)))
            .to.emit(guardian, "EnvelopeExecuted");
    });

    it("rejects an envelope with an unenforceable slippage bound", async () => {
        const { user, guardian, makeEnvelope, swapData } = await loadFixture(deployFixture);
        const { envelope, signature } = await makeEnvelope({ maxSlippageBps: 10_000n });
        const amountIn = ethers.parseEther("100");

        await expect(
            guardian.connect(user).execute(envelope, signature, amountIn, swapData(amountIn))
        ).to.be.revertedWithCustomError(guardian, "InvalidSlippageBps");
    });
});
