// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title Guardian — on-chain enforcement of Ward Safety Envelopes
/// @notice The Ward copilot (running in a TEE) analyses a user's intent and signs a
///         SafetyEnvelope: hard guarantees about what a transaction is allowed to do.
///         Guardian executes the transaction only within those guarantees and reverts
///         the moment reality violates any of them. The copilot promises; the chain enforces.
contract Guardian is EIP712, Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    struct SafetyEnvelope {
        address user; // who may execute this envelope
        address target; // the only contract this envelope may call
        bytes4 selector; // the only function this envelope may call
        address tokenIn; // asset being spent (address(0) = native)
        uint256 maxAmountIn; // hard cap on spend
        address tokenOut; // asset expected back (address(0) = native)
        uint256 minOut; // minimum received, or the whole tx reverts
        uint256 deadline; // envelope expiry (unix seconds)
        uint256 nonce; // single-use: no replays
    }

    bytes32 public constant ENVELOPE_TYPEHASH =
        keccak256(
            "SafetyEnvelope(address user,address target,bytes4 selector,address tokenIn,uint256 maxAmountIn,address tokenOut,uint256 minOut,uint256 deadline,uint256 nonce)"
        );

    /// @notice Key held by the attested Ward agent inside the TEE.
    address public wardSigner;

    mapping(address user => mapping(uint256 nonce => bool)) public usedNonces;

    error NotEnvelopeUser(address caller, address expected);
    error EnvelopeExpired(uint256 deadline, uint256 nowTs);
    error EnvelopeAlreadyUsed(uint256 nonce);
    error SelectorNotAllowed(bytes4 given, bytes4 allowed);
    error ExceedsMaxSpend(uint256 requested, uint256 maxAmountIn);
    error InvalidWardSignature();
    error InsufficientOutput(uint256 received, uint256 minOut);
    error NativeValueMismatch();

    event WardSignerUpdated(address indexed signer);
    event EnvelopeExecuted(
        address indexed user,
        bytes32 indexed envelopeHash,
        address target,
        uint256 amountIn,
        uint256 amountOut
    );

    constructor(address _wardSigner) EIP712("Ward Guardian", "1") Ownable(msg.sender) {
        wardSigner = _wardSigner;
        emit WardSignerUpdated(_wardSigner);
    }

    function setWardSigner(address _wardSigner) external onlyOwner {
        wardSigner = _wardSigner;
        emit WardSignerUpdated(_wardSigner);
    }

    function hashEnvelope(SafetyEnvelope calldata env) public view returns (bytes32) {
        return
            _hashTypedDataV4(
                keccak256(
                    abi.encode(
                        ENVELOPE_TYPEHASH,
                        env.user,
                        env.target,
                        env.selector,
                        env.tokenIn,
                        env.maxAmountIn,
                        env.tokenOut,
                        env.minOut,
                        env.deadline,
                        env.nonce
                    )
                )
            );
    }

    /// @notice Execute `data` against the envelope's target under its guarantees.
    /// @param env the Safety Envelope signed by the Ward agent
    /// @param wardSig EIP-712 signature over the envelope by `wardSigner`
    /// @param amountIn how much of `tokenIn` to spend (must be <= env.maxAmountIn)
    /// @param data calldata for the target; output tokens must be sent to this contract
    function execute(
        SafetyEnvelope calldata env,
        bytes calldata wardSig,
        uint256 amountIn,
        bytes calldata data
    ) external payable nonReentrant returns (uint256 amountOut) {
        bytes32 envelopeHash = _authorize(env, wardSig, amountIn, data);

        uint256 outBefore = _balance(env.tokenOut);
        _pullInputAndCall(env, amountIn, data);
        if (env.tokenIn != address(0)) _settleInput(env, outBefore);

        amountOut = _balance(env.tokenOut) - outBefore;
        if (amountOut < env.minOut) revert InsufficientOutput(amountOut, env.minOut);
        _payout(env.tokenOut, env.user, amountOut);

        emit EnvelopeExecuted(env.user, envelopeHash, env.target, amountIn, amountOut);
    }

    /// @dev Checks every envelope guarantee that can be verified before the call,
    ///      burns the nonce, and returns the envelope hash for the event.
    function _authorize(
        SafetyEnvelope calldata env,
        bytes calldata wardSig,
        uint256 amountIn,
        bytes calldata data
    ) internal returns (bytes32 envelopeHash) {
        if (msg.sender != env.user) revert NotEnvelopeUser(msg.sender, env.user);
        if (block.timestamp > env.deadline) revert EnvelopeExpired(env.deadline, block.timestamp);
        if (usedNonces[env.user][env.nonce]) revert EnvelopeAlreadyUsed(env.nonce);
        bytes4 given = bytes4(data[:4]);
        if (given != env.selector) revert SelectorNotAllowed(given, env.selector);
        if (amountIn > env.maxAmountIn) revert ExceedsMaxSpend(amountIn, env.maxAmountIn);

        envelopeHash = hashEnvelope(env);
        if (ECDSA.recover(envelopeHash, wardSig) != wardSigner) revert InvalidWardSignature();
        usedNonces[env.user][env.nonce] = true;
    }

    function _pullInputAndCall(
        SafetyEnvelope calldata env,
        uint256 amountIn,
        bytes calldata data
    ) internal {
        uint256 callValue = 0;
        if (env.tokenIn == address(0)) {
            if (msg.value != amountIn) revert NativeValueMismatch();
            callValue = amountIn;
        } else {
            if (msg.value != 0) revert NativeValueMismatch();
            IERC20(env.tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
            IERC20(env.tokenIn).forceApprove(env.target, amountIn);
        }

        (bool ok, bytes memory ret) = env.target.call{value: callValue}(data);
        if (!ok) {
            assembly {
                revert(add(ret, 32), mload(ret))
            }
        }
    }

    /// @dev Revokes the target's approval and refunds any input the target did not pull.
    function _settleInput(SafetyEnvelope calldata env, uint256 outBefore) internal {
        IERC20(env.tokenIn).forceApprove(env.target, 0);
        uint256 leftoverIn = IERC20(env.tokenIn).balanceOf(address(this));
        if (env.tokenIn == env.tokenOut) leftoverIn = leftoverIn > outBefore ? 0 : leftoverIn;
        if (leftoverIn > 0) IERC20(env.tokenIn).safeTransfer(env.user, leftoverIn);
    }

    function _balance(address token) internal view returns (uint256) {
        return token == address(0) ? address(this).balance : IERC20(token).balanceOf(address(this));
    }

    function _payout(address token, address to, uint256 amount) internal {
        if (token == address(0)) {
            (bool ok, ) = to.call{value: amount}("");
            require(ok, "Guardian: native payout failed");
        } else {
            IERC20(token).safeTransfer(to, amount);
        }
    }

    receive() external payable {}
}
