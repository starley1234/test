// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title AGI Progress Oracle
/// @notice The viral heart of WenAGI: a single on-chain number, 0–10000 bps,
///         answering the oldest question in crypto — "wen AGI?".
///         An oracle (backend multisig) moves the needle as real AI usage
///         accumulates. Every burned $WAGI pushes humanity closer.
///
///         Eras (fixed on-chain thresholds by cumulative burn):
///           0.00%  Chatbots       — "it can talk"
///           6.00%  Agents         — "it can act"
///          13.00%  Recursion      — "it improves itself"
///          22.00%  The Squeeze    — "it out-codes your team"
///          34.00%  Ghost Labor    — "your job runs at 3 AM"
///          48.00%  Symmetry       — "it negotiates for you"
///          63.00%  Cascade        — "AI builds AI"
///          79.00%  Last Problem   — "it solves what we could not"
///          94.00%  Silence        — "it stopped answering. it works."
///         100.00% AGI            — wen.
contract AGIProgressOracle {
    struct Era {
        uint128 burnedThreshold; // cumulative $WAGI burned (18 decimals)
        string name;
        string quip;
    }

    address public owner;
    address public oracle; // backend signer allowed to nudge the needle
    uint16 public progressBps; // 0 .. 10_000, the answer to "wen AGI?"
    uint256 public updatedAt;
    string public narrative = "Chatbots";

    /// @dev Ordered by burnedThreshold ascending, fixed at deploy.
    Era[] private _eras;

    event ProgressUpdated(uint16 indexed oldBps, uint16 indexed newBps, string narrative, uint256 burnedTotal, uint256 timestamp);
    event OracleUpdated(address indexed previous, address indexed next);
    event OwnershipTransferred(address indexed previous, address indexed next);

    error OnlyOwner();
    error OnlyOracle();
    error ZeroAddress();
    error TooHigh(uint16 bps);
    error TooFarBack(uint16 newBps, uint16 currentBps);

    modifier onlyOwner() {
        if (msg.sender != owner) revert OnlyOwner();
        _;
    }

    modifier onlyOracle() {
        if (msg.sender != oracle) revert OnlyOracle();
        _;
    }

    constructor(address oracle_) {
        if (oracle_ == address(0)) revert ZeroAddress();
        owner = msg.sender;
        oracle = oracle_;
        _seedEras();
    }

    function _seedEras() internal {
        uint128 w = 1 ether; // one whole $WAGI
        Era[10] memory seed = [
            Era(0, "Chatbots", "it can talk"),
            Era(50_000 * w, "Agents", "it can act"),
            Era(150_000 * w, "Recursion", "it improves itself"),
            Era(300_000 * w, "The Squeeze", "it out-codes your team"),
            Era(500_000 * w, "Ghost Labor", "your job runs at 3 AM"),
            Era(700_000 * w, "Symmetry", "it negotiates for you"),
            Era(850_000 * w, "Cascade", "AI builds AI"),
            Era(940_000 * w, "Last Problem", "it solves what we could not"),
            Era(990_000 * w, "Silence", "it stopped answering. it works."),
            Era(999_999 * w, "AGI", "wen.")
        ];
        for (uint256 i = 0; i < seed.length; i++) {
            _eras.push(seed[i]);
        }
    }

    // ------------------------------------------------------------- live views
    function eraCount() external view returns (uint256) {
        return _eras.length;
    }

    function eraAt(uint256 i) external view returns (uint128 burnedThreshold, string memory name, string memory quip) {
        Era storage e = _eras[i];
        return (e.burnedThreshold, e.name, e.quip);
    }

    /// @notice Era index implied purely by cumulative burned $WAGI.
    ///         Pure function — anyone can compute it from InferenceMarket.
    function eraForBurned(uint256 burnedTotal) public view returns (uint256 idx) {
        for (uint256 i = _eras.length; i > 0; i--) {
            if (burnedTotal >= _eras[i - 1].burnedThreshold) return i - 1;
        }
        return 0;
    }

    /// @notice Convenience view for dashboards and the leaderboard widget.
    ///         Compose with InferenceMarket.burnedTotal() for the live era.
    function snapshot(uint256 burnedTotal)
        external
        view
        returns (uint16 bps, string memory eraName, string memory eraQuip, uint256 updated, string memory currentNarrative)
    {
        uint256 idx = eraForBurned(burnedTotal);
        Era storage e = _eras[idx];
        return (progressBps, e.name, e.quip, updatedAt, narrative);
    }

    // ---------------------------------------------------------------- updates
    /// @param newBps       New progress in bps. May move up, or down by at
    ///                     most 100 bps per update (reality isn't monotonic,
    ///                     but the oracle can't rug the narrative).
    /// @param narrative_   Short human-readable note ("GPT-6 shipped", ...).
    /// @param burnedTotal_ Cumulative burned $WAGI at sign time (analytics).
    function update(uint16 newBps, string calldata narrative_, uint256 burnedTotal_) external onlyOracle {
        if (newBps > 10_000) revert TooHigh(newBps);
        if (uint256(newBps) + 100 < uint256(progressBps)) revert TooFarBack(newBps, progressBps);
        emit ProgressUpdated(progressBps, newBps, narrative_, burnedTotal_, block.timestamp);
        progressBps = newBps;
        narrative = narrative_;
        updatedAt = block.timestamp;
    }

    function setOracle(address next) external onlyOwner {
        if (next == address(0)) revert ZeroAddress();
        emit OracleUpdated(oracle, next);
        oracle = next;
    }

    /// @notice Hand ownership to the DAO multisig. The multisig itself can
    ///         correct any mistake by a threshold decision.
    function transferOwnership(address next) external onlyOwner {
        if (next == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, next);
        owner = next;
    }
}
