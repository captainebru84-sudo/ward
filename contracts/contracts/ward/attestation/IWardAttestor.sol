// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

interface IWardAttestor {
    /// @notice Verifies a Google Confidential Space attestation token (JWT) and
    ///         returns the enclave's signer address from its `eat_nonce` claim.
    /// @param rawHeader JWT header, Base64URL-decoded
    /// @param rawPayload JWT payload, Base64URL-decoded
    /// @param signature RS256 signature, Base64URL-decoded
    function verifyAttestation(bytes calldata rawHeader, bytes calldata rawPayload, bytes calldata signature)
        external
        view
        returns (address enclaveSigner);
}
