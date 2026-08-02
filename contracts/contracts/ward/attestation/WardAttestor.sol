// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Base64} from "@openzeppelin/contracts/utils/Base64.sol";
import {RSA} from "@openzeppelin/contracts/utils/cryptography/RSA.sol";
import {IWardAttestor} from "./IWardAttestor.sol";
import {ParserUtils} from "./utils/ParserUtils.sol";

/// @title WardAttestor — on-chain verification of Google Confidential Space attestations
/// @notice Verifies an RS256-signed Confidential Space attestation token against
///         Google's published signing keys and a required workload configuration
///         (issuer, TEE hardware, secure boot, container image digest), then returns
///         the enclave's ephemeral signer address from the token's `eat_nonce` claim.
///
///         Vendored and trimmed from flare-foundation/flare-vtpm-attestation (MIT):
///         - single non-upgradeable contract; OIDC (RS256) tokens only, no PKI path
///         - attestation is bound to `eat_nonce` instead of msg.sender. The reference
///           registers the quote for whoever submits it, but JWTs are public calldata,
///           so anyone can replay one. Here the workload places its signer address
///           INSIDE the Google-signed payload (as the requested nonce), so a token
///           always resolves to the key the enclave actually holds — anyone may relay
///           it, and replaying it is harmless.
contract WardAttestor is IWardAttestor, Ownable {
    struct RequiredConfig {
        bytes iss;
        bytes hwmodel;
        bytes swname;
        bytes imageDigest;
        bool secboot;
    }

    struct RSAPubKey {
        bytes e; // exponent
        bytes n; // modulus
    }

    /// @notice Google's JWT signing keys (from the Confidential Computing JWKS), by kid.
    mapping(bytes kid => RSAPubKey) public pubKeys;

    /// @notice Claims a token must carry to be accepted.
    RequiredConfig public requiredConfig;

    error SignatureVerificationFailed(string reason);
    error PayloadValidationFailed(string reason);

    event PubKeyAdded(bytes kid);
    event PubKeyRemoved(bytes kid);
    event RequiredConfigUpdated(string iss, string hwmodel, string swname, string imageDigest, bool secboot);

    constructor(
        string memory iss,
        string memory hwmodel,
        string memory swname,
        string memory imageDigest,
        bool secboot
    ) Ownable(msg.sender) {
        _setRequiredConfig(iss, hwmodel, swname, imageDigest, secboot);
    }

    /// @notice Updates the required claims, e.g. after releasing a new agent image.
    function setRequiredConfig(
        string calldata iss,
        string calldata hwmodel,
        string calldata swname,
        string calldata imageDigest,
        bool secboot
    ) external onlyOwner {
        _setRequiredConfig(iss, hwmodel, swname, imageDigest, secboot);
    }

    /// @notice Registers a Google signing key from the Confidential Computing JWKS.
    function addPubKey(bytes calldata kid, bytes calldata e, bytes calldata n) external onlyOwner {
        pubKeys[kid] = RSAPubKey({e: e, n: n});
        emit PubKeyAdded(kid);
    }

    function removePubKey(bytes calldata kid) external onlyOwner {
        delete pubKeys[kid];
        emit PubKeyRemoved(kid);
    }

    /// @inheritdoc IWardAttestor
    function verifyAttestation(bytes calldata rawHeader, bytes calldata rawPayload, bytes calldata signature)
        external
        view
        returns (address enclaveSigner)
    {
        // 1. Google's RS256 signature covers base64url(header).base64url(payload)
        bytes memory kid = ParserUtils.extractStringValue(rawHeader, '"kid":"');
        RSAPubKey storage pubKey = pubKeys[kid];
        if (pubKey.n.length == 0) {
            revert SignatureVerificationFailed("unknown kid");
        }
        bytes memory signingInput =
            abi.encodePacked(Base64.encodeURL(rawHeader), ".", Base64.encodeURL(rawPayload));
        if (!RSA.pkcs1Sha256(sha256(signingInput), signature, pubKey.e, pubKey.n)) {
            revert SignatureVerificationFailed("invalid signature");
        }

        // 2. the signed claims must match the required workload configuration
        _validatePayload(rawPayload);

        // 3. the enclave put its signer address in the token as the requested nonce
        enclaveSigner = ParserUtils.extractAddressValue(rawPayload, '"eat_nonce":"');
    }

    function _validatePayload(bytes calldata rawPayload) internal view {
        if (ParserUtils.extractUintValue(rawPayload, '"exp":') < block.timestamp) {
            revert PayloadValidationFailed("token expired");
        }
        if (ParserUtils.extractUintValue(rawPayload, '"iat":') > block.timestamp) {
            revert PayloadValidationFailed("token not yet valid");
        }
        RequiredConfig storage required = requiredConfig;
        if (keccak256(ParserUtils.extractStringValue(rawPayload, '"iss":"')) != keccak256(required.iss)) {
            revert PayloadValidationFailed("invalid issuer");
        }
        if (ParserUtils.extractBoolValue(rawPayload, '"secboot":') != required.secboot) {
            revert PayloadValidationFailed("invalid secboot");
        }
        if (keccak256(ParserUtils.extractStringValue(rawPayload, '"hwmodel":"')) != keccak256(required.hwmodel)) {
            revert PayloadValidationFailed("invalid hardware model");
        }
        if (keccak256(ParserUtils.extractStringValue(rawPayload, '"swname":"')) != keccak256(required.swname)) {
            revert PayloadValidationFailed("invalid software name");
        }
        if (
            keccak256(ParserUtils.extractStringValue(rawPayload, '"image_digest":"'))
                != keccak256(required.imageDigest)
        ) {
            revert PayloadValidationFailed("invalid image digest");
        }
    }

    function _setRequiredConfig(
        string memory iss,
        string memory hwmodel,
        string memory swname,
        string memory imageDigest,
        bool secboot
    ) internal {
        requiredConfig = RequiredConfig({
            iss: bytes(iss),
            hwmodel: bytes(hwmodel),
            swname: bytes(swname),
            imageDigest: bytes(imageDigest),
            secboot: secboot
        });
        emit RequiredConfigUpdated(iss, hwmodel, swname, imageDigest, secboot);
    }
}
