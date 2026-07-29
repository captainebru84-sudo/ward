// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract MockERC20 is ERC20 {
    constructor(string memory name_, string memory symbol_) ERC20(name_, symbol_) {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

/// @notice Minimal DEX for Guardian tests. Rate is settable so tests can simulate
///         price moves / sandwich attacks between envelope signing and execution.
contract MockDEX {
    uint256 public rate; // amountOut = amountIn * rate / 1e18

    constructor(uint256 _rate) {
        rate = _rate;
    }

    function setRate(uint256 _rate) external {
        rate = _rate;
    }

    function swap(address tokenIn, address tokenOut, uint256 amountIn) external returns (uint256 out) {
        IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn);
        out = (amountIn * rate) / 1e18;
        MockERC20(tokenOut).mint(msg.sender, out);
    }

    /// @notice A function no honest envelope would ever allow — used to prove selector blocking.
    function drainApproval(address token, address victim) external {
        IERC20(token).transferFrom(victim, address(this), IERC20(token).balanceOf(victim));
    }
}

/// @notice Minimal FTSO v2 stand-in exposing the one method Guardian consumes.
///         Feed values and decimals are settable so tests can move the "market".
contract MockFtsoV2 {
    struct Feed {
        uint256 value;
        int8 decimals;
    }

    mapping(bytes21 => Feed) public feeds;

    function setFeed(bytes21 id, uint256 value, int8 decimals_) external {
        feeds[id] = Feed(value, decimals_);
    }

    function getFeedsById(
        bytes21[] calldata ids
    ) external view returns (uint256[] memory values, int8[] memory decimals_, uint64 timestamp) {
        values = new uint256[](ids.length);
        decimals_ = new int8[](ids.length);
        for (uint256 i = 0; i < ids.length; i++) {
            values[i] = feeds[ids[i]].value;
            decimals_[i] = feeds[ids[i]].decimals;
        }
        timestamp = uint64(block.timestamp);
    }
}
