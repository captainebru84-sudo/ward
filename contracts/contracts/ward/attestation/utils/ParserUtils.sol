// SPDX-License-Identifier: MIT
// Vendored from flare-foundation/flare-vtpm-attestation (MIT), with
// extractAddressValue/parseAddress added for eat_nonce extraction.
pragma solidity ^0.8.25;

library ParserUtils {
    error InvalidAddressValue();

    /**
     * @dev Extracts a value from a JSON-like byte array by locating a specific key and delimiter.
     * @param data The byte array containing the JSON-like data.
     * @param key The key to search for, formatted with any required preceding characters, e.g., '":'.
     * @param delimiter The character that indicates the end of the value.
     * @return value The extracted value associated with the key, returned as a bytes array.
     */
    function extractValue(bytes calldata data, string memory key, string memory delimiter)
        internal
        pure
        returns (bytes memory value)
    {
        bytes memory keyBytes = bytes(key);
        bytes memory delimiterBytes = bytes(delimiter);

        uint256 start = indexOf(data, keyBytes);
        if (start == type(uint256).max) {
            return ""; // Key not found
        }
        start += keyBytes.length;

        uint256 end = indexOf(data[start:], delimiterBytes);
        if (end == type(uint256).max) {
            return ""; // Delimiter not found
        }
        value = data[start:start + end];
    }

    /// @dev Extracts a string value for `key`, using `"` as the closing delimiter.
    function extractStringValue(bytes calldata data, string memory key) internal pure returns (bytes memory result) {
        return extractValue(data, key, '"');
    }

    /// @dev Extracts a boolean value for `key`, assuming it is followed by a comma.
    function extractBoolValue(bytes calldata data, string memory key) internal pure returns (bool result) {
        bytes memory stringValue = extractValue(data, key, ",");
        return parseBool(stringValue);
    }

    /// @dev Extracts a uint256 value for `key`, assuming it is followed by a comma.
    function extractUintValue(bytes calldata data, string memory key) internal pure returns (uint256 result) {
        bytes memory stringValue = extractValue(data, key, ",");
        return parseUint(stringValue);
    }

    /// @dev Extracts a 0x-prefixed hex address string for `key` and parses it.
    function extractAddressValue(bytes calldata data, string memory key) internal pure returns (address result) {
        return parseAddress(extractStringValue(data, key));
    }

    /// @dev Parses a byte array of ASCII digits into a uint256; stops at the first non-digit.
    function parseUint(bytes memory numBytes) internal pure returns (uint256 result) {
        for (uint256 i = 0; i < numBytes.length; i++) {
            uint8 c = uint8(numBytes[i]);
            if (c >= 48 && c <= 57) {
                // '0' to '9' in ASCII
                result = result * 10 + (c - 48);
            } else {
                break; // Stop parsing when a non-digit is encountered
            }
        }
    }

    /// @dev Parses 'true'/'false' bytes into a boolean; anything but 'true' is false.
    function parseBool(bytes memory boolBytes) internal pure returns (bool result) {
        if (
            boolBytes.length == 4 // Length of 'true'
                && boolBytes[0] == "t" && boolBytes[1] == "r" && boolBytes[2] == "u" && boolBytes[3] == "e"
        ) {
            return true;
        }
        return false;
    }

    /// @dev Parses a 42-character, 0x-prefixed hex string (any letter case) into an address.
    function parseAddress(bytes memory hexBytes) internal pure returns (address result) {
        if (hexBytes.length != 42 || hexBytes[0] != "0" || hexBytes[1] != "x") {
            revert InvalidAddressValue();
        }
        uint160 acc = 0;
        for (uint256 i = 2; i < 42; i++) {
            acc = acc * 16 + uint160(parseNibble(uint8(hexBytes[i])));
        }
        result = address(acc);
    }

    function parseNibble(uint8 c) private pure returns (uint8) {
        if (c >= 48 && c <= 57) return c - 48; // '0'-'9'
        if (c >= 97 && c <= 102) return c - 87; // 'a'-'f'
        if (c >= 65 && c <= 70) return c - 55; // 'A'-'F'
        revert InvalidAddressValue();
    }

    /// @dev Returns true if `needle` occurs within `haystack`.
    function contains(bytes calldata haystack, bytes memory needle) internal pure returns (bool exists) {
        return indexOf(haystack, needle) != type(uint256).max;
    }

    /// @dev Index of the first occurrence of `needle` in `haystack`, or uint256.max if absent.
    function indexOf(bytes calldata haystack, bytes memory needle) internal pure returns (uint256 index) {
        if (needle.length == 0 || haystack.length < needle.length) {
            return type(uint256).max;
        }

        for (uint256 i = 0; i <= haystack.length - needle.length; i++) {
            bool found = true;
            for (uint256 j = 0; j < needle.length; j++) {
                if (haystack[i + j] != needle[j]) {
                    found = false;
                    break;
                }
            }
            if (found) {
                return i;
            }
        }
        return type(uint256).max;
    }
}
