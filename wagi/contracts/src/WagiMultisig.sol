// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title WagiMultisig — on-chain-confirmation multisig wallet for WenAGI
///        roles (treasury / relayer / oracle governance).
/// @notice Classic wallet-style multisig: an owner submits a transaction
///         (destination, value, calldata), owners confirm on-chain, and once
///         `required` confirmations are collected ANYONE may execute it.
///         Administrative actions (owner set / threshold changes) are
///         performed by the wallet calling itself through the same
///         submit→confirm→execute pipeline, so every change leaves an
///         on-chain audit trail signed by the threshold.
/// @dev Self-contained on purpose: no external dependencies, minimal audit
///      surface. For very large mainnet treasuries, a battle-tested Safe
///      (safe.global) is an equally valid replacement — the WenAGI suite
///      treats any address as treasury/relayer/oracle.
contract WagiMultisig {
    struct Transaction {
        address dest;
        uint256 value;
        bytes data;
        bool executed;
    }

    uint256 public constant MAX_OWNER_COUNT = 50;

    mapping(address owner => bool) public isOwner;
    address[] private _owners;
    uint256 public required; // confirmation threshold
    uint256 public transactionCount;

    mapping(uint256 txId => Transaction) public transactions;
    mapping(uint256 txId => mapping(address owner => bool)) public confirmations;

    event Submission(uint256 indexed txId, address indexed dest, uint256 value, bytes data);
    event Confirmation(address indexed sender, uint256 indexed txId);
    event Revocation(address indexed sender, uint256 indexed txId);
    event Execution(uint256 indexed txId, bytes returnData);
    event Deposit(address indexed sender, uint256 value);
    event OwnerAddition(address indexed owner);
    event OwnerRemoval(address indexed owner);
    event OwnerReplacement(address indexed oldOwner, address indexed newOwner);
    event RequirementChange(uint256 required);

    error NotOwner(address sender);
    error NotSelf(address sender);
    error ZeroAddress();
    error OwnerLimitExceeded(uint256 count);
    error AlreadyOwner(address owner);
    error NotAnOwner(address owner);
    error InvalidThreshold(uint256 required, uint256 ownerCount);
    error TxNotFound(uint256 txId);
    error TxAlreadyExecuted(uint256 txId);
    error AlreadyConfirmed(uint256 txId, address sender);
    error NotConfirmed(uint256 txId, address sender);
    error NotEnoughConfirmations(uint256 have, uint256 need);
    error CallFailed(bytes reason);

    modifier onlyOwner() {
        if (!isOwner[msg.sender]) revert NotOwner(msg.sender);
        _;
    }

    /// @dev Some admin functions may only be reached by the wallet executing
    ///      a confirmed transaction whose destination is the wallet itself.
    modifier onlyWallet() {
        if (msg.sender != address(this)) revert NotSelf(msg.sender);
        _;
    }

    /// @param owners_   Initial owner set (no zero addresses, no duplicates).
    /// @param required_ Confirmation threshold, 1 <= required_ <= owners.
    constructor(address[] memory owners_, uint256 required_) {
        if (owners_.length == 0 || owners_.length > MAX_OWNER_COUNT) revert OwnerLimitExceeded(owners_.length);
        for (uint256 i = 0; i < owners_.length; i++) {
            address owner = owners_[i];
            if (owner == address(0)) revert ZeroAddress();
            if (isOwner[owner]) revert AlreadyOwner(owner);
            isOwner[owner] = true;
            _owners.push(owner);
            emit OwnerAddition(owner);
        }
        if (required_ == 0 || required_ > owners_.length) revert InvalidThreshold(required_, owners_.length);
        required = required_;
        emit RequirementChange(required_);
    }

    receive() external payable {
        emit Deposit(msg.sender, msg.value);
    }

    // ------------------------------------------------------------ tx lifecycle
    /// @notice Submit a transaction; the submitter is auto-confirmed.
    function submitTransaction(address dest, uint256 value, bytes calldata data) external onlyOwner returns (uint256 txId) {
        txId = transactionCount;
        transactions[txId] = Transaction({dest: dest, value: value, data: data, executed: false});
        unchecked {
            transactionCount += 1;
        }
        emit Submission(txId, dest, value, data);
        confirmTransaction(txId);
    }

    function confirmTransaction(uint256 txId) public onlyOwner {
        if (txId >= transactionCount) revert TxNotFound(txId);
        if (confirmations[txId][msg.sender]) revert AlreadyConfirmed(txId, msg.sender);
        confirmations[txId][msg.sender] = true;
        emit Confirmation(msg.sender, txId);
    }

    function revokeConfirmation(uint256 txId) public onlyOwner {
        if (txId >= transactionCount) revert TxNotFound(txId);
        if (!confirmations[txId][msg.sender]) revert NotConfirmed(txId, msg.sender);
        confirmations[txId][msg.sender] = false;
        emit Revocation(msg.sender, txId);
    }

    /// @notice Execute once `required` confirmations have been collected.
    ///         Callable by anyone (relayer bots may sponsor gas).
    function executeTransaction(uint256 txId) external {
        if (txId >= transactionCount) revert TxNotFound(txId);
        Transaction storage t = transactions[txId];
        if (t.executed) revert TxAlreadyExecuted(txId);

        uint256 have = 0;
        for (uint256 i = 0; i < _owners.length; i++) {
            if (confirmations[txId][_owners[i]]) have += 1;
        }
        if (have < required) revert NotEnoughConfirmations(have, required);

        t.executed = true;
        (bool ok, bytes memory ret) = t.dest.call{value: t.value}(t.data);
        if (!ok) revert CallFailed(ret);
        emit Execution(txId, ret);
    }

    // ------------------------------------------------------------------ views
    function getOwners() external view returns (address[] memory) {
        return _owners;
    }

    function ownerCount() external view returns (uint256) {
        return _owners.length;
    }

    function getConfirmationCount(uint256 txId) external view returns (uint256 count) {
        for (uint256 i = 0; i < _owners.length; i++) {
            if (confirmations[txId][_owners[i]]) count += 1;
        }
    }

    function getTransaction(uint256 txId)
        external
        view
        returns (address dest, uint256 value, bytes memory data, bool executed)
    {
        Transaction storage t = transactions[txId];
        return (t.dest, t.value, t.data, t.executed);
    }

    // ------------------------------------------------- admin via self-call
    /// @dev Only reachable when the wallet executes a transaction targeting
    ///      itself (dest == address(this)).
    function addOwner(address owner) external onlyWallet {
        if (owner == address(0)) revert ZeroAddress();
        if (isOwner[owner]) revert AlreadyOwner(owner);
        if (_owners.length >= MAX_OWNER_COUNT) revert OwnerLimitExceeded(_owners.length);
        isOwner[owner] = true;
        _owners.push(owner);
        emit OwnerAddition(owner);
    }

    function removeOwner(address owner) external onlyWallet {
        if (!isOwner[owner]) revert NotAnOwner(owner);
        if (_owners.length - 1 < required) revert InvalidThreshold(required, _owners.length - 1);
        isOwner[owner] = false;
        _removeFromArray(owner);
        emit OwnerRemoval(owner);
    }

    function replaceOwner(address oldOwner, address newOwner) external onlyWallet {
        if (!isOwner[oldOwner]) revert NotAnOwner(oldOwner);
        if (newOwner == address(0)) revert ZeroAddress();
        if (isOwner[newOwner]) revert AlreadyOwner(newOwner);
        isOwner[oldOwner] = false;
        isOwner[newOwner] = true;
        uint256 len = _owners.length;
        for (uint256 i = 0; i < len; i++) {
            if (_owners[i] == oldOwner) {
                _owners[i] = newOwner;
                break;
            }
        }
        emit OwnerReplacement(oldOwner, newOwner);
    }

    function changeThreshold(uint256 required_) external onlyWallet {
        if (required_ == 0 || required_ > _owners.length) revert InvalidThreshold(required_, _owners.length);
        required = required_;
        emit RequirementChange(required_);
    }

    function _removeFromArray(address owner) private {
        uint256 len = _owners.length;
        for (uint256 i = 0; i < len; i++) {
            if (_owners[i] == owner) {
                _owners[i] = _owners[len - 1];
                _owners.pop();
                return;
            }
        }
    }
}
