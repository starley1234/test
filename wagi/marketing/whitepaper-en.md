# WenAGI ($WAGI) — Whitepaper
### The token that burns its way to AGI

**Version:** 1.0 · **Status:** mainnet-ready · **Chain:** Base (EVM, OP-stack)

## 1. The problem

The two defining phenomena of the decade — **crypto** and **LLMs** — barely touch:

- AI inference is paid for with bank cards through closed gateways. For
  non-humans (agents, bots, autonomous services) that's a dead end: a machine
  has no card.
- Meme coins have no utility. AI coins often have no reason to exist as coins.
  Both lose half their potential.

## 2. The solution

**WenAGI is a decentralized LLM inference marketplace where the unit of
account is $WAGI.**

1. A developer (or an AI agent) gets an API key and pays **$WAGI per request**
   at an OpenAI-compatible gateway.
2. Every fee is split on-chain by the **InferenceMarket** contract:
   **80%** to the GPU provider that served the request, **15%** to the DAO
   treasury, **5% burned forever**.
3. Network progress is published by the **AGIProgressOracle** — a single
   0–100% number answering crypto's oldest question: **"wen AGI?"**

## 3. Why it goes viral

| Mechanic | Effect |
|---|---|
| **Live AGI progress bar** | One shared scoreboard for the whole internet: "we're at 7.3%". |
| **Progress share-card** | Users share a PNG: "my prompts burned N $WAGI" (Spotify Wrapped × crypto). |
| **Prompt wall** | A public anonymized feed of the network's queries — endless screenshot fuel. |
| **Burning as ritual** | Every prompt irreversibly shrinks supply. Users compete to burn. |
| **Utility quests** | Airdrop points are earned by making real requests, not clicking. |
| **Name & mascot** | "WEN AGI?" is a phrase crypto has said for a decade. WAGI-1 is the robot who waits. |

## 4. Tokenomics

**Supply:** 1,000,000,000 $WAGI, minted once; no mint function exists.

| Share | Purpose | Terms |
|---|---|---|
| 40% | Inference rewards | 5 years, for useful compute |
| 15% | Airdrop | merkle claim, gasless (permit) |
| 15% | Liquidity | 80/20 pools, locked 2 years |
| 12% | Team | 6-month cliff, 24-month on-chain vesting |
| 10% | DAO treasury | grants, audits, listings |
| 8% | Investors | 18-month vesting |

**Deflation:** 5% of every fee is burned. At 10M requests/day with a 0.3 WAGI
average fee the network burns ~150K WAGI/day. Usage grows → supply shrinks →
fiat price of inference can fall while the $WAGI economy grows.

## 5. Architecture

```
Agent/app ──HTTPS──► WenAGI Gateway (OpenAI-compatible)
                        │ token metering, $WAGI billing
                        ▼
                  InferenceMarket.sol (Base)
                  ├── 80% to GPU provider
                  ├── 15% to DAO treasury
                  └── 5% BURN ──► AGIProgressOracle.sol
                                   "wen AGI?" → 0..100%
```

Contracts (`contracts/src/`): WagiToken (ERC-20 + EIP-2612 + burn),
InferenceMarket (fee split + replay-protected settlement incl. atomic `settleBatch` up to 100 prompts/tx), AGIProgressOracle
(10 eras by cumulative burn), WagiAirdrop (merkle, double-claim proof),
TokenVesting (cliff + linear, revocable), WagiMultisig (on-chain-confirmation
multisig: submit → confirmations → execute; admin only via self-calls).

**Governance:** no EOA holds a privilege — TreasuryMultisig 3/5 (DAO, owns
every contract), RelayerMultisig 2/3 (batch settlement), OracleMultisig 2/3
(progress updates).

Tests: 44/44 green (`cd contracts && npm test`), including property-based invariants and full multisig
governance integration (quorum, revocation, self-call admin, and the proof
that a single key can never move funds or the narrative).

## 6. Roadmap

- **Phase 0 (done):** contracts + tests + demo gateway + playground.
- **Phase 1 (T-14d):** viral wave, quests, 100K followers.
- **Phase 2 (TGE):** audit → Base deploy → 80/20 pool → gasless claims.
- **Phase 3 (+30d):** mainnet gateway, real models, on-chain settlement, SDK.
- **Phase 4 (+90d):** GPU marketplace — rent your GPU, earn $WAGI.
- **Phase 5 (WEN):** AGI. The bar reaches the end. We promise to promise
  nothing.

## 7. Risks & honesty

- Contracts are **unaudited**; audit is scheduled before TGE.
- The relayer is trusted for token metering but can never move funds beyond
  the user-approved fee.
- The AGI bar is a narrative index of real burns, not a scientific metric.
  We say so openly — honesty is part of the brand.
- NFA.

**WEN AGI? WEN $WAGI.**
