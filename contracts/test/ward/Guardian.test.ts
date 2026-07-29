import { loadFixture, time } from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { expect } from "chai";
import { ethers } from "hardhat";

const RATE = ethers.parseEther("2"); // 1 IN -> 2 OUT

async function deployFixture() {
    const [owner, user, attacker] = await ethers.getSigners();
    // In production this key lives inside the TEE; here it's a plain test signer.
    const wardAgent = ethers.Wallet.createRandom().connect(ethers.provider);

    const tokenIn = await (await ethers.getContractFactory("MockERC20")).deploy("USDCoin", "USDC");
    const tokenOut = await (await ethers.getContractFactory("MockERC20")).deploy("Wrapped FLR", "WFLR");
    const dex = await (await ethers.getContractFactory("MockDEX")).deploy(RATE);
    const guardian = await (await ethers.getContractFactory("Guardian")).deploy(wardAgent.address);

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

    return { owner, user, attacker, wardAgent, tokenIn, tokenOut, dex, guardian, makeEnvelope, swapData };
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
});
