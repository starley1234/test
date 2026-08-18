// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title WenAGI Token ($WAGI)
/// @notice Fixed-supply ERC-20 that powers the WenAGI decentralized LLM inference
///         network. No mint function exists after deployment: every inference
///         request burns a slice of the fee, making $WAGI deflationary as AI
///         usage grows. Includes EIP-2612 permit for gasless airdrop claims.
/// @dev Self-contained (no external dependencies) to keep the audit surface
///      minimal. Custom errors are used instead of require strings for gas.
contract WagiToken {
    // ---------------------------------------------------------------- metadata
    string public constant name = "WenAGI";
    string public constant symbol = "WAGI";
    uint8 public constant decimals = 18;

    /// @notice Hard cap. Can never be increased — there is no mint().
    uint256 public constant MAX_SUPPLY = 1_000_000_000 * 10 ** 18;

    // ------------------------------------------------------------------ state
    uint256 public totalSupply;
    mapping(address account => uint256) public balanceOf;
    mapping(address owner => mapping(address spender => uint256)) public allowance;
    mapping(address owner => uint256) public nonces;

    // ------------------------------------------------------------------ events
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event Burned(address indexed account, uint256 value);

    // ------------------------------------------------------------------ errors
    error InvalidSender(); // ERC-20: transfer from the zero address
    error InvalidReceiver(); // ERC-20: transfer to the zero address
    error InsufficientBalance(uint256 available, uint256 needed);
    error InsufficientAllowance(uint256 available, uint256 needed);
    error PermitExpired(uint256 deadline, uint256 now_);
    error PermitInvalidSigner(address recovered, address owner);
    error PermitInvalidSignature();
    error SafeApproveSpam(uint256 currentAllowance);

    // -------------------------------------------------------------- EIP-2612
    bytes32 public constant PERMIT_TYPEHASH =
        keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)");
    bytes32 private constant _DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    string private constant _VERSION = "1";

    /// @dev Reconstructed on every call so the token survives chain forks.
    function DOMAIN_SEPARATOR() public view returns (bytes32) {
        return keccak256(
            abi.encode(
                _DOMAIN_TYPEHASH,
                keccak256(bytes(name)),
                keccak256(bytes(_VERSION)),
                block.chainid,
                address(this)
            )
        );
    }

    // ------------------------------------------------------------- constructor
    /// @param treasury Receiver of the entire fixed supply (DAO / distributor).
    constructor(address treasury) {
        if (treasury == address(0)) revert InvalidReceiver();
        totalSupply = MAX_SUPPLY;
        balanceOf[treasury] = MAX_SUPPLY;
        emit Transfer(address(0), treasury, MAX_SUPPLY);
    }

    // -------------------------------------------------------------- ERC-20 core
    function transfer(address to, uint256 value) public virtual returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) public virtual returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed < value) revert InsufficientAllowance(allowed, value);
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - value;
            emit Approval(from, msg.sender, allowed - value);
        }
        _transfer(from, to, value);
        return true;
    }

    function approve(address spender, uint256 value) public virtual returns (bool) {
        _approve(msg.sender, spender, value);
        return true;
    }

    /// @notice approve which reverts if the current allowance is non-zero
    ///         (mitigates the race condition described in ERC-20 API report).
    function safeApprove(address spender, uint256 value) external returns (bool) {
        uint256 current = allowance[msg.sender][spender];
        if (current != 0 && value != 0) revert SafeApproveSpam(current);
        _approve(msg.sender, spender, value);
        return true;
    }

    function _approve(address owner, address spender, uint256 value) internal {
        if (owner == address(0)) revert InvalidSender();
        if (spender == address(0)) revert InvalidReceiver();
        allowance[owner][spender] = value;
        emit Approval(owner, spender, value);
    }

    function _transfer(address from, address to, uint256 value) internal {
        if (from == address(0)) revert InvalidSender();
        if (to == address(0)) revert InvalidReceiver();
        uint256 fromBalance = balanceOf[from];
        if (fromBalance < value) revert InsufficientBalance(fromBalance, value);
        unchecked {
            balanceOf[from] = fromBalance - value;
            balanceOf[to] += value;
        }
        emit Transfer(from, to, value);
    }

    // ------------------------------------------------------------------- burn
    /// @notice Destroy tokens permanently. Each inference fee burns 5%,
    ///         so total supply shrinks as the network approaches AGI.
    function burn(uint256 value) external {
        uint256 fromBalance = balanceOf[msg.sender];
        if (fromBalance < value) revert InsufficientBalance(fromBalance, value);
        unchecked {
            balanceOf[msg.sender] = fromBalance - value;
            totalSupply -= value;
        }
        emit Transfer(msg.sender, address(0), value);
        emit Burned(msg.sender, value);
    }

    // ----------------------------------------------------------------- permit
    function permit(
        address owner,
        address spender,
        uint256 value,
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external {
        if (block.timestamp > deadline) revert PermitExpired(deadline, block.timestamp);
        bytes32 structHash =
            keccak256(abi.encode(PERMIT_TYPEHASH, owner, spender, value, nonces[owner], deadline));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR(), structHash));
        address recovered = ecrecover(digest, v, r, s);
        if (recovered == address(0)) revert PermitInvalidSignature();
        if (recovered != owner) revert PermitInvalidSigner(recovered, owner);
        nonces[owner] += 1;
        _approve(owner, spender, value);
    }
}
