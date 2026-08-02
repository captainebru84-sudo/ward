import { loadFixture, time } from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { expect } from "chai";
import { ethers } from "hardhat";
import * as fs from "fs";
import * as path from "path";

// The real attestation token minted by our agent inside Confidential Space,
// and the Google signing key (from the Confidential Computing JWKS) that signed it.
const sample = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../../../agent/attestation_sample.json"), "utf8")
);
const jwks = JSON.parse(
    fs.readFileSync(path.join(__dirname, "fixtures/google_jwks_snapshot.json"), "utf8")
);

const [headerB64, payloadB64, signatureB64] = sample.token.split(".");
const header = Buffer.from(headerB64, "base64url");
const payload = Buffer.from(payloadB64, "base64url");
const signature = Buffer.from(signatureB64, "base64url");
const claims = JSON.parse(payload.toString());
const kid: string = JSON.parse(header.toString()).kid;
const googleKey = jwks.sampleTokenKey;

const ENCLAVE_SIGNER = ethers.getAddress(claims.eat_nonce);
const IMAGE_DIGEST_V1 = claims.submods.container.image_digest;
const REQUIRED = [
    claims.iss, // iss
    claims.hwmodel, // hwmodel: GCP_INTEL_TDX
    claims.swname, // swname: CONFIDENTIAL_SPACE
    IMAGE_DIGEST_V1, // image digest the token attests
    true, // secboot
] as const;

async function deployFixture() {
    const [owner, anyone] = await ethers.getSigners();

    const attestor = await (await ethers.getContractFactory("WardAttestor")).deploy(...REQUIRED);
    await attestor.addPubKey(
        ethers.toUtf8Bytes(kid),
        Buffer.from(googleKey.e, "base64url"),
        Buffer.from(googleKey.n, "base64url")
    );

    const ftso = await (await ethers.getContractFactory("MockFtsoV2")).deploy();
    const initialSigner = ethers.Wallet.createRandom().address;
    const guardian = await (
        await ethers.getContractFactory("Guardian")
    ).deploy(initialSigner, await ftso.getAddress());
    await guardian.setAttestor(await attestor.getAddress());

    return { owner, anyone, attestor, guardian, initialSigner };
}

describe("WardAttestor", () => {
    it("runs inside the sample token's validity window (fixture sanity)", async () => {
        const now = await time.latest();
        expect(now, "hardhat initialDate must sit inside the token's iat..exp window").to.be.within(
            claims.iat,
            claims.exp
        );
    });

    it("verifies the real Google-signed token and returns the enclave signer", async () => {
        const { attestor } = await loadFixture(deployFixture);
        expect(await attestor.verifyAttestation(header, payload, signature)).to.equal(ENCLAVE_SIGNER);
    });

    it("rejects a payload tampered with after signing", async () => {
        const { attestor } = await loadFixture(deployFixture);
        // attacker swaps in their own address as the enclave signer
        const tampered = Buffer.from(
            payload.toString().replace(claims.eat_nonce, "0xdEaD74067F0c46204fB5fDd6531eb42d91a7821C")
        );
        await expect(attestor.verifyAttestation(header, tampered, signature))
            .to.be.revertedWithCustomError(attestor, "SignatureVerificationFailed")
            .withArgs("invalid signature");
    });

    it("rejects a token signed by an unregistered key", async () => {
        const { owner, attestor } = await loadFixture(deployFixture);
        await attestor.connect(owner).removePubKey(ethers.toUtf8Bytes(kid));
        await expect(attestor.verifyAttestation(header, payload, signature))
            .to.be.revertedWithCustomError(attestor, "SignatureVerificationFailed")
            .withArgs("unknown kid");
    });

    it("rejects an expired token", async () => {
        const { attestor } = await loadFixture(deployFixture);
        await time.increaseTo(claims.exp + 1);
        await expect(attestor.verifyAttestation(header, payload, signature))
            .to.be.revertedWithCustomError(attestor, "PayloadValidationFailed")
            .withArgs("token expired");
    });

    it("rejects a token attesting a different container image", async () => {
        const { attestor } = await loadFixture(deployFixture);
        await attestor.setRequiredConfig(
            REQUIRED[0],
            REQUIRED[1],
            REQUIRED[2],
            "sha256:4b84dab800000000000000000000000000000000000000000000000000000000",
            REQUIRED[4]
        );
        await expect(attestor.verifyAttestation(header, payload, signature))
            .to.be.revertedWithCustomError(attestor, "PayloadValidationFailed")
            .withArgs("invalid image digest");
    });

    it("only the owner can manage keys and config", async () => {
        const { anyone, attestor } = await loadFixture(deployFixture);
        await expect(
            attestor.connect(anyone).addPubKey("0x00", "0x010001", "0x00")
        ).to.be.revertedWithCustomError(attestor, "OwnableUnauthorizedAccount");
        await expect(
            attestor.connect(anyone).setRequiredConfig("x", "x", "x", "x", false)
        ).to.be.revertedWithCustomError(attestor, "OwnableUnauthorizedAccount");
    });
});

describe("Guardian.rotateSignerByAttestation", () => {
    it("lets ANYONE rotate the ward signer with a valid attestation", async () => {
        const { anyone, guardian, initialSigner } = await loadFixture(deployFixture);
        expect(await guardian.wardSigner()).to.equal(initialSigner);

        await expect(guardian.connect(anyone).rotateSignerByAttestation(header, payload, signature))
            .to.emit(guardian, "WardSignerAttested")
            .withArgs(ENCLAVE_SIGNER);
        expect(await guardian.wardSigner()).to.equal(ENCLAVE_SIGNER);
    });

    it("replaying the same token is harmless: it resolves to the same enclave key", async () => {
        const { anyone, guardian } = await loadFixture(deployFixture);
        await guardian.connect(anyone).rotateSignerByAttestation(header, payload, signature);
        await guardian.connect(anyone).rotateSignerByAttestation(header, payload, signature);
        expect(await guardian.wardSigner()).to.equal(ENCLAVE_SIGNER);
    });

    it("propagates attestor rejections", async () => {
        const { anyone, guardian, attestor } = await loadFixture(deployFixture);
        const tampered = Buffer.from(
            payload.toString().replace(claims.eat_nonce, "0xdEaD74067F0c46204fB5fDd6531eb42d91a7821C")
        );
        await expect(
            guardian.connect(anyone).rotateSignerByAttestation(header, tampered, signature)
        ).to.be.revertedWithCustomError(attestor, "SignatureVerificationFailed");
    });

    it("reverts when no attestor is configured", async () => {
        const { anyone } = await loadFixture(deployFixture);
        const ftso = await (await ethers.getContractFactory("MockFtsoV2")).deploy();
        const bare = await (
            await ethers.getContractFactory("Guardian")
        ).deploy(ethers.Wallet.createRandom().address, await ftso.getAddress());
        await expect(
            bare.connect(anyone).rotateSignerByAttestation(header, payload, signature)
        ).to.be.revertedWithCustomError(bare, "AttestorNotSet");
    });
});
