// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

interface IWagi {
    function transferFrom(address from, address to, uint256 value) external returns (bool);
    function transfer(address to, uint256 value) external returns (bool);
    function burn(uint256 value) external;
}

/// @title WenAGI Inference Market
/// @notice On-chain settlement layer for pay-per-prompt LLM inference.
///         Users approve $WAGI to this contract; an audited relayer (the
///         WenAGI gateway) settles completed requests and splits the fee:
///
///             80% -> GPU provider   (the one who served the tokens)
///             15% -> treasury       (DAO: grants, liquidity, safety budget)
///              5% -> BURN           (deflationary flywheel)
///
///         Only a keccak256 hash of the prompt ever touches the chain,
///         so user content stays private while usage stays verifiable.
/// @dev The relayer is trusted for *pricing honesty* (off-chain metering) but
///      can never move funds beyond the user-approved fee. Multisig-owned.
contract InferenceMarket {
    IWagi public immutable wagi;
    address public owner;
    address public relayer;
    address public treasury;

    uint256 public providerBps = 8_000; // 80.00%
    uint256 public treasuryBps = 1_500; // 15.00%
    uint256 public burnBps = 500; //  5.00%

    mapping(address => bool) public isProvider;
    address[] public providerList;

    uint256 public settledRequests;
    uint256 public burnedTotal; // cumulative $WAGI incinerated by inference
    uint256 public feesTotal; // cumulative fees settled
    mapping(bytes32 promptHash => bool settled) public settledPrompt;

    event OwnershipTransferred(address indexed previous, address indexed next);
    event RelayerUpdated(address indexed previous, address indexed next);
    event TreasuryUpdated(address indexed previous, address indexed next);
    event FeeSplitUpdated(uint256 providerBps, uint256 treasuryBps, uint256 burnBps);
    event ProviderRegistered(address indexed provider);
    event ProviderRemoved(address indexed provider);
    event PromptSettled(
        address indexed user,
        address indexed provider,
        bytes32 indexed promptHash,
        uint256 fee,
        uint256 providerPart,
        uint256 treasuryPart,
        uint256 burnPart,
        uint64 tokensIn,
        uint64 tokensOut
    );

    error OnlyOwner();
    error OnlyRelayer();
    error ZeroAddress();
    error BadSplit(uint256 sum);
    error UnknownProvider(address provider);
    error PromptAlreadySettled(bytes32 promptHash);
    error ZeroFee();

    modifier onlyOwner() {
        if (msg.sender != owner) revert OnlyOwner();
        _;
    }

    modifier onlyRelayer() {
        if (msg.sender != relayer) revert OnlyRelayer();
        _;
    }

    constructor(IWagi wagi_, address treasury_, address relayer_) {
        if (address(wagi_) == address(0) || treasury_ == address(0) || relayer_ == address(0)) {
            revert ZeroAddress();
        }
        wagi = wagi_;
        treasury = treasury_;
        relayer = relayer_;
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
        emit TreasuryUpdated(address(0), treasury_);
        emit RelayerUpdated(address(0), relayer_);
    }

    // ------------------------------------------------------------------ admin
    function transferOwnership(address next) external onlyOwner {
        if (next == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, next);
        owner = next;
    }

    function setRelayer(address next) external onlyOwner {
        if (next == address(0)) revert ZeroAddress();
        emit RelayerUpdated(relayer, next);
        relayer = next;
    }

    function setTreasury(address next) external onlyOwner {
        if (next == address(0)) revert ZeroAddress();
        emit TreasuryUpdated(treasury, next);
        treasury = next;
    }

    /// @notice Update the fee split. Must always sum to exactly 100%.
    function setFeeSplit(uint256 providerBps_, uint256 treasuryBps_, uint256 burnBps_) external onlyOwner {
        if (providerBps_ + treasuryBps_ + burnBps_ != 10_000) revert BadSplit(providerBps_ + treasuryBps_ + burnBps_);
        if (burnBps_ < 100) revert BadSplit(burnBps_); // burn can never drop below 1%
        providerBps = providerBps_;
        treasuryBps = treasuryBps_;
        burnBps = burnBps_;
        emit FeeSplitUpdated(providerBps_, treasuryBps_, burnBps_);
    }

    function registerProvider(address provider) external onlyOwner {
        if (provider == address(0)) revert ZeroAddress();
        if (isProvider[provider]) return;
        isProvider[provider] = true;
        providerList.push(provider);
        emit ProviderRegistered(provider);
    }

    function removeProvider(address provider) external onlyOwner {
        if (!isProvider[provider]) revert UnknownProvider(provider);
        isProvider[provider] = false;
        emit ProviderRemoved(provider);
    }

    function providerCount() external view returns (uint256) {
        return providerList.length;
    }

    // -------------------------------------------------------------- settlement
    /// @notice Settle one completed inference request.
    /// @param user        The requester; must have approved this contract >= fee.
    /// @param provider    Registered GPU provider that served the request.
    /// @param promptHash  keccak256(user || nonce || prompt || model) — privacy
    ///                    preserving, replay-protected fingerprint.
    /// @param fee         Total fee in $WAGI wei.
    /// @param tokensIn    Metered prompt tokens.
    /// @param tokensOut   Metered completion tokens.
    function settle(
        address user,
        address provider,
        bytes32 promptHash,
        uint256 fee,
        uint64 tokensIn,
        uint64 tokensOut
    ) external onlyRelayer {
        _settle(user, provider, promptHash, fee, tokensIn, tokensOut);
    }

    /// @dev Batch limit — bound worst-case gas per settlement transaction.
    uint256 public constant MAX_BATCH = 100;

    /// @notice One request settled by the gateway (relayer metering).
    struct PromptBill {
        address user;
        address provider;
        bytes32 promptHash;
        uint256 fee;
        uint64 tokensIn;
        uint64 tokensOut;
    }

    error BadBatchSize(uint256 size);

    /// @notice Settle a batch of completed requests in one transaction.
    ///         Atomic: if ANY entry is invalid (unknown provider, replayed
    ///         hash, insufficient allowance) the whole batch reverts —
    ///         the gateway retries it after fixing the offending entry.
    ///         Cuts per-request gas by an order of magnitude on Base.
    function settleBatch(PromptBill[] calldata batch) external onlyRelayer {
        uint256 n = batch.length;
        if (n == 0 || n > MAX_BATCH) revert BadBatchSize(n);
        for (uint256 i = 0; i < n; i++) {
            PromptBill calldata b = batch[i];
            _settle(b.user, b.provider, b.promptHash, b.fee, b.tokensIn, b.tokensOut);
        }
    }

    function _settle(
        address user,
        address provider,
        bytes32 promptHash,
        uint256 fee,
        uint64 tokensIn,
        uint64 tokensOut
    ) internal {
        if (fee == 0) revert ZeroFee();
        if (!isProvider[provider]) revert UnknownProvider(provider);
        if (settledPrompt[promptHash]) revert PromptAlreadySettled(promptHash);
        settledPrompt[promptHash] = true;

        wagi.transferFrom(user, address(this), fee);

        uint256 providerPart = (fee * providerBps) / 10_000;
        uint256 treasuryPart = (fee * treasuryBps) / 10_000;
        uint256 burnPart = fee - providerPart - treasuryPart; // exact, no dust lost

        wagi.transfer(provider, providerPart);
        wagi.transfer(treasury, treasuryPart);
        wagi.burn(burnPart);

        unchecked {
            settledRequests += 1;
            burnedTotal += burnPart;
            feesTotal += fee;
        }

        emit PromptSettled(user, provider, promptHash, fee, providerPart, treasuryPart, burnPart, tokensIn, tokensOut);
    }

    /// @notice Emergency rescue for tokens sent by mistake (never $WAGI).
    function rescue(IWagi token, address to, uint256 amount) external onlyOwner {
        if (address(token) == address(wagi)) revert ZeroAddress();
        token.transfer(to, amount);
    }
}
