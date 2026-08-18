// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

interface IWagiTransfer {
    function transfer(address to, uint256 value) external returns (bool);
}

/// @title WenAGI Merkle Airdrop
/// @notice Gas-efficient viral airdrop. The distributor publishes a merkle
///         root of keccak256(keccak256(addr, amount)) leaves; winners claim
///         in one tx. Double-claims are impossible by design.
contract WagiAirdrop {
    IWagiTransfer public immutable wagi;
    address public owner;
    bytes32 public merkleRoot;
    mapping(address claimant => bool) public claimed;

    event RootSet(bytes32 indexed root, uint256 totalLeaves);
    event Claimed(address indexed claimant, uint256 amount);
    event Recovered(address indexed to, uint256 amount);
    event OwnershipTransferred(address indexed previous, address indexed next);

    error OnlyOwner();
    error ZeroAddress();
    error RootNotSet();
    error AlreadyClaimed();
    error InvalidProof();

    modifier onlyOwner() {
        if (msg.sender != owner) revert OnlyOwner();
        _;
    }

    constructor(IWagiTransfer wagi_, bytes32 merkleRoot_, uint256 totalLeaves) {
        if (address(wagi_) == address(0)) revert ZeroAddress();
        wagi = wagi_;
        owner = msg.sender;
        merkleRoot = merkleRoot_;
        if (merkleRoot_ != bytes32(0)) emit RootSet(merkleRoot_, totalLeaves);
    }

    /// @notice Claim your drop. Generate proofs with
    ///         `node scripts/airdrop-tree.js` (off-chain distributor).
    function claim(uint256 amount, bytes32[] calldata proof) external {
        if (merkleRoot == bytes32(0)) revert RootNotSet();
        if (claimed[msg.sender]) revert AlreadyClaimed();
        claimed[msg.sender] = true;

        bytes32 leaf = keccak256(bytes.concat(keccak256(abi.encode(msg.sender, amount))));
        if (!_verify(proof, leaf)) revert InvalidProof();

        emit Claimed(msg.sender, amount);
        wagi.transfer(msg.sender, amount);
    }

    /// @notice Replace the root (e.g. snapshot re-run before TGE). Claims
    ///         already made stay marked, so abuse requires a fresh set.
    function setRoot(bytes32 root, uint256 totalLeaves) external onlyOwner {
        merkleRoot = root;
        emit RootSet(root, totalLeaves);
    }

    /// @notice Hand ownership to the DAO multisig.
    function transferOwnership(address next) external onlyOwner {
        if (next == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, next);
        owner = next;
    }

    /// @notice Recover unclaimed tokens after the window closes (to DAO).
    function recover(address to, uint256 amount) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        emit Recovered(to, amount);
        wagi.transfer(to, amount);
    }

    function _verify(bytes32[] calldata proof, bytes32 leaf) internal view returns (bool) {
        bytes32 computed = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 p = proof[i];
            if (computed < p) {
                computed = keccak256(bytes.concat(computed, p));
            } else {
                computed = keccak256(bytes.concat(p, computed));
            }
        }
        return computed == merkleRoot;
    }
}
