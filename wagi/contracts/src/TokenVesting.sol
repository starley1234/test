// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

interface IWagiVest {
    function transfer(address to, uint256 value) external returns (bool);
}

/// @title WenAGI Token Vesting
/// @notice Linear vesting with cliff for team, investors and advisors.
///         Commitment transparency is a listing requirement on every major
///         exchange — holders can verify unlocks on-chain.
contract TokenVesting {
    struct Vest {
        uint128 total; // total locked amount
        uint64 start; // vesting clock start (ts)
        uint64 cliff; // seconds from start until first unlock
        uint64 duration; // seconds from start to fully vested
        bool revocable;
        bool revoked;
        uint128 released; // already withdrawn
        uint128 vestedAtRevoke; // frozen claimable amount if revoked
    }

    IWagiVest public immutable wagi;
    address public owner;

    mapping(address beneficiary => Vest) public vests;

    event VestCreated(address indexed beneficiary, uint256 total, uint64 start, uint64 cliff, uint64 duration, bool revocable);
    event Released(address indexed beneficiary, uint256 amount);
    event Revoked(address indexed beneficiary, uint256 refunded);
    event OwnershipTransferred(address indexed previous, address indexed next);

    error OnlyOwner();
    error ZeroAddress();
    error ZeroAmount();
    error AlreadyVested();
    error BadSchedule();
    error NothingToRelease();
    error NotRevocable();
    error NothingToRevoke();

    modifier onlyOwner() {
        if (msg.sender != owner) revert OnlyOwner();
        _;
    }

    constructor(IWagiVest wagi_) {
        if (address(wagi_) == address(0)) revert ZeroAddress();
        wagi = wagi_;
        owner = msg.sender;
    }

    /// @notice Hand ownership to the DAO multisig.
    function transferOwnership(address next) external onlyOwner {
        if (next == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, next);
        owner = next;
    }

    /// @notice Create a linear vesting schedule. Treasury must fund this
    ///         contract with the total amount beforehand.
    function create(
        address beneficiary,
        uint128 total,
        uint64 start,
        uint64 cliff, // seconds from start
        uint64 duration, // seconds from start to fully vested
        bool revocable
    ) external onlyOwner {
        if (beneficiary == address(0)) revert ZeroAddress();
        if (total == 0) revert ZeroAmount();
        if (vests[beneficiary].total != 0) revert AlreadyVested();
        if (duration == 0 || duration < cliff) revert BadSchedule();

        vests[beneficiary] = Vest({
            total: total,
            start: start,
            cliff: cliff,
            duration: duration,
            revocable: revocable,
            revoked: false,
            released: 0,
            vestedAtRevoke: 0
        });
        emit VestCreated(beneficiary, total, start, cliff, duration, revocable);
    }

    /// @notice Amount currently claimable by `beneficiary`.
    function vested(address beneficiary) public view returns (uint256) {
        Vest storage v = vests[beneficiary];
        if (v.total == 0) return 0;
        if (v.revoked) return v.vestedAtRevoke;
        if (block.timestamp < v.start + v.cliff) return 0;
        if (block.timestamp >= v.start + v.duration) return v.total;
        return (uint256(v.total) * (block.timestamp - v.start)) / v.duration;
    }

    /// @notice Beneficiary withdraws everything currently vested.
    function release() external {
        Vest storage v = vests[msg.sender];
        uint256 claimable = vested(msg.sender) - v.released;
        if (claimable == 0) revert NothingToRelease();
        v.released += uint128(claimable);
        wagi.transfer(msg.sender, claimable);
        emit Released(msg.sender, claimable);
    }

    /// @notice Owner cancels a revocable schedule; unvested tokens are
    ///         refunded. The amount vested up to this second stays claimable.
    function revoke(address beneficiary) external onlyOwner {
        Vest storage v = vests[beneficiary];
        if (v.total == 0) revert NothingToRevoke();
        if (!v.revocable) revert NotRevocable();
        uint256 vestedSoFar = vested(beneficiary);
        v.revoked = true;
        v.vestedAtRevoke = uint128(vestedSoFar);
        uint256 refundable = uint256(v.total) - vestedSoFar;
        if (refundable > 0) wagi.transfer(owner, refundable);
        emit Revoked(beneficiary, refundable);
    }
}
