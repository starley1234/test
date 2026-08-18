import { test } from "node:test";
import assert from "node:assert/strict";
import {
  feeFor,
  splitFee,
  progressBpsFor,
  eraForBurned,
  estimateTokens,
} from "../src/pricing.js";

test("fee matches published pricing with minimum floor", () => {
  // 2M input + 1M output = 2*50 + 150 = 250 WAGI
  assert.equal(feeFor(2_000_000, 1_000_000), 250);
  // tiny requests hit the floor
  assert.equal(feeFor(10, 10), 0.1);
});

test("split is exact: no dust lost", () => {
  for (const fee of [0.1, 1, 1.234567, 250, 0.000001]) {
    const p = splitFee(fee);
    // reconstruct fee in micro-units exactly like the contract
    const micro = Math.round(fee * 1e6);
    assert.equal(Math.round(p.provider * 1e6) + Math.round(p.treasury * 1e6) + Math.round(p.burn * 1e6), micro);
  }
});

test("split ratios follow 80/15/5 (micro-precision fees excepted)", () => {
  for (const fee of [0.1, 1, 1.234567, 250, 12.5]) {
    const p = splitFee(fee);
    assert.ok(p.provider / fee > 0.799 && p.provider / fee <= 0.8);
    assert.ok(p.burn / fee >= 0.04999 && p.burn / fee <= 0.05001);
  }
});

test("progress bar moves with burns and caps at 99.90%", () => {
  assert.equal(progressBpsFor(0), 0);
  assert.equal(progressBpsFor(500_000), 5000);
  assert.equal(progressBpsFor(1_000_000), 9990);
  assert.equal(progressBpsFor(5_000_000), 9990); // the last 0.1% belongs to AGI itself
});

test("eras match the on-chain thresholds", () => {
  assert.equal(eraForBurned(0).name, "Chatbots");
  assert.equal(eraForBurned(49_999).name, "Chatbots");
  assert.equal(eraForBurned(50_000).name, "Agents");
  assert.equal(eraForBurned(999_000).name, "AGI");
});

test("token estimation is sane", () => {
  assert.ok(estimateTokens("hello world") >= 3);
  assert.equal(estimateTokens(""), 1);
});
