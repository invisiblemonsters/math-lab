# PaymentSplitter

**Contract:** `0x4b2875409d89Fea624daD45c585667D6f533361D` on Base L2

A gas-optimized payment splitting utility. Send tokens once, distribute to up to 50 recipients in a single transaction. 0.1% fee.

## Features

- **Multi-recipient**: Split payments among up to 50 addresses in one tx
- **ERC20 + Native ETH**: Works with any ERC20 token or native ETH
- **Proportional shares**: Recipients get proportional shares — no need to sum to 100
- **Low fee**: 0.1% (10 bps), configurable up to 1%
- **Owner-controlled**: Fee withdrawal and fee rate changes are owner-only
- **Immutable core**: No upgrade proxy, no pause, no kill switch
- **Gas optimized**: Single loop over recipients, no external calls except token transfers

## How It Works

1. **Sender** approves the PaymentSplitter contract to spend their tokens (or sends ETH)
2. **Sender** calls `split(token, recipients, shares)` 
3. Each recipient receives `(amount * share / totalShares)` minus the fee
4. The 0.1% fee stays in the contract — owner withdraws later via `withdrawFees(token)`

## Contract Interface

```solidity
function split(
    address token,           // ERC20 address (0x0 for ETH)
    address[] calldata recipients,  // Up to 50 addresses
    uint256[] calldata shares      // Proportional shares
) external payable;

function withdrawFees(address token) external;
function setFee(uint256 newFeeBps) external;  // Max 100 (1%)
function transferOwnership(address newOwner) external;
```

## Usage Example

```python
# Split 1000 USDC among 3 team members (50/30/20 split)
usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
splitter = "0x4b2875409d89Fea624daD45c585667D6f533361D"
team = ["0xAlice...", "0xBob...", "0xCarol..."]
shares = [50, 30, 20]

# 1. Approve splitter
usdc_contract.functions.approve(splitter, 1000 * 10**6).transact()

# 2. Send tokens to splitter
usdc_contract.functions.transfer(splitter, 1000 * 10**6).transact()

# 3. Execute split
splitter_contract.functions.split(usdc, team, shares).transact()
```

## Fees

- **Current fee**: 0.1% (10 bps)
- **Max fee**: 1% (hardcoded — `MAX_FEE = 100`)
- Fees accumulate per-token in the contract
- Owner can withdraw accumulated fees at any time

## Security

- No `delegatecall`, no selfdestruct, no assembly
- Owner cannot steal user funds — only withdraw accumulated fees
- Fee capped at 1% maximum
- Recipients array capped at 50 (gas limit protection)
- Standard OpenZeppelin-compatible ownership pattern

## Deployment

- **Chain**: Base (Chain ID 8453)
- **Address**: `0x4b2875409d89Fea624daD45c585667D6f533361D`
- **Deployer**: `0x11B185ceFcB2A001FFDddf0f226437D16EbF5437`
- **Basescan**: https://basescan.org/address/0x4b2875409d89Fea624daD45c585667D6f533361D

## Use Cases

- Team payroll / revenue sharing
- Royalty splits for NFT collections
- DAO grant distributions
- Affiliate / referral payouts
- Group expense splitting

## License

MIT
