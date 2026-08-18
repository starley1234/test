// WenAGI pricing & fee accounting — pure functions, fully unit-tested.
// Mirrors the on-chain InferenceMarket split: 80% provider / 15% treasury / 5% burn.

export const PRICING = {
  // $WAGI per 1M tokens — deliberately cheap: mainnet settlement for AI calls
  inputPerMillion: 50, // WAGI
  outputPerMillion: 150, // WAGI
  minFee: 0.1, // WAGI per request
  decimals: 18,
};

export const SPLIT = {
  providerBps: 8000,
  treasuryBps: 1500,
  burnBps: 500,
};

export const MAX_SUPPLY = 1_000_000_000; // 1B WAGI
export const BURN_TARGET = 1_000_000; // burned WAGI at which the bar hits ~100%

export function weiToWagi(hexOrBig) {
  return Number(BigInt(hexOrBig)) / 10 ** PRICING.decimals;
}

/// Estimate tokens (chars/4 heuristic when no tokenizer is shipped).
export function estimateTokens(text) {
  return Math.max(1, Math.ceil(String(text ?? "").length / 4));
}

/// Exact fee in WAGI (rounded to 6 decimals) for metered token counts.
export function feeFor(tokensIn, tokensOut) {
  const fee =
    (tokensIn / 1e6) * PRICING.inputPerMillion + (tokensOut / 1e6) * PRICING.outputPerMillion;
  return Math.round(Math.max(fee, PRICING.minFee) * 1e6) / 1e6;
}

/// Split a fee according to the on-chain split. No dust is lost.
export function splitFee(fee) {
  const micro = Math.round(fee * 1e6);
  const provider = Math.floor((micro * SPLIT.providerBps) / 10000);
  const treasury = Math.floor((micro * SPLIT.treasuryBps) / 10000);
  const burn = micro - provider - treasury; // exact remainder — mirrors Solidity
  return {
    provider: provider / 1e6,
    treasury: treasury / 1e6,
    burn: burn / 1e6,
  };
}

/// The viral metric: 0..10000 bps of progress toward AGI from cumulative burn.
export function progressBpsFor(burnedWagi) {
  const bps = Math.floor((Math.min(burnedWagi, BURN_TARGET) / BURN_TARGET) * 10_000);
  return Math.min(bps, 9990); // the last 0.1% is reserved for the real thing
}

/// Era thresholds — must mirror AGIProgressOracle._seedEras().
export const ERAS = [
  { burned: 0, name: "Chatbots", quip: "it can talk" },
  { burned: 50_000, name: "Agents", quip: "it can act" },
  { burned: 150_000, name: "Recursion", quip: "it improves itself" },
  { burned: 300_000, name: "The Squeeze", quip: "it out-codes your team" },
  { burned: 500_000, name: "Ghost Labor", quip: "your job runs at 3 AM" },
  { burned: 700_000, name: "Symmetry", quip: "it negotiates for you" },
  { burned: 850_000, name: "Cascade", quip: "AI builds AI" },
  { burned: 940_000, name: "Last Problem", quip: "it solves what we could not" },
  { burned: 990_000, name: "Silence", quip: "it stopped answering. it works." },
  { burned: 999_000, name: "AGI", quip: "wen." },
];

export function eraForBurned(burnedWagi) {
  let idx = 0;
  for (let i = 0; i < ERAS.length; i++) if (burnedWagi >= ERAS[i].burned) idx = i;
  return ERAS[idx];
}
