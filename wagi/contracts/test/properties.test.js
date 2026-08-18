// Property-based tests: randomized invariants, deterministic and reproducible.
import { expect } from "chai";
import { deploy, as, walletClient, expectRevert } from "./helpers.js";
import { encodeFunctionData } from "viem";
import { buildTree, makeLeaf, verifyProof } from "../scripts/lib/merkle.js";

const ONE = 10n ** 18n;

/// Deterministic PRNG (mulberry32) so failures print a reproducible seed.
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe("InferenceMarket.settleBatch — batch settlement", () => {
  let token, market, treasury, relayer, user, providerA, providerB;

  beforeEach(async () => {
    treasury = await walletClient(0);
    relayer = await walletClient(1);
    user = await walletClient(2);
    providerA = await walletClient(3);
    providerB = await walletClient(4);
    token = await deploy("WagiToken", [treasury.account.address]);
    market = await deploy("InferenceMarket", [
      token.address,
      treasury.account.address,
      relayer.account.address,
    ]);
    await token.write.transfer([user.account.address, 10_000n * ONE]);
    await market.write.registerProvider([providerA.account.address]);
    await market.write.registerProvider([providerB.account.address]);
  });

  async function relayerMarket() {
    return as("InferenceMarket", market.address, relayer);
  }

  it("settles 3 mixed requests in one tx with exact accounting", async () => {
    const userToken = await as("WagiToken", token.address, user);
    await userToken.write.approve([market.address, 300n * ONE]);

    const batch = [
      [user.account.address, providerA.account.address, "0x" + "01".repeat(32), 100n * ONE, 10n, 20n],
      [user.account.address, providerB.account.address, "0x" + "02".repeat(32), 50n * ONE, 5n, 5n],
      [user.account.address, providerA.account.address, "0x" + "03".repeat(32), 25n * ONE, 1n, 1n],
    ];
    await (await relayerMarket()).write.settleBatch([batch]);

    // providers: A 80+20, B 40
    expect(await token.read.balanceOf([providerA.account.address])).to.equal(100n * ONE);
    expect(await token.read.balanceOf([providerB.account.address])).to.equal(40n * ONE);
    // treasury: 15 + 7.5 + 3.75
    expect(await market.read.settledRequests()).to.equal(3n);
    expect(await market.read.feesTotal()).to.equal(175n * ONE);
    // burn: 5% of 175 = 8.75
    expect(await market.read.burnedTotal()).to.equal(875n * ONE / 100n);
    expect(await token.read.totalSupply()).to.equal(1_000_000_000n * ONE - 875n * ONE / 100n);
  });

  it("is atomic: one replayed hash reverts the entire batch", async () => {
    const userToken = await as("WagiToken", token.address, user);
    await userToken.write.approve([market.address, 400n * ONE]);

    await (await relayerMarket()).write.settle([
      user.account.address,
      providerA.account.address,
      "0x" + "aa".repeat(32),
      10n * ONE,
      1n,
      1n,
    ]);
    expect(await market.read.settledRequests()).to.equal(1n);

    // batch contains the already-settled hash -> everything reverts
    const batch = [
      [user.account.address, providerA.account.address, "0x" + "bb".repeat(32), 10n * ONE, 1n, 1n],
      [user.account.address, providerA.account.address, "0x" + "aa".repeat(32), 10n * ONE, 1n, 1n],
    ];
    const rm = await relayerMarket();
    await expectRevert(() => rm.write.settleBatch([batch]), "PromptAlreadySettled", market);
    expect(await market.read.settledRequests()).to.equal(1n); // nothing changed
    expect(await market.read.burnedTotal()).to.equal(10n * ONE / 20n); // only the first settle's 5%

    // after removing the offending entry the same batch settles fine
    const clean = [batch[0]];
    await (await relayerMarket()).write.settleBatch([clean]);
    expect(await market.read.settledRequests()).to.equal(2n);
  });

  it("rejects empty and oversized batches", async () => {
    const rm = await relayerMarket();
    await expectRevert(() => rm.write.settleBatch([[]]), "BadBatchSize", market);

    const oversized = Array.from({ length: 101 }, (_, i) => [
      user.account.address,
      providerA.account.address,
      "0x" + (i + 1).toString(16).padStart(64, "0"),
      1n * ONE,
      1n,
      1n,
    ]);
    await expectRevert(() => rm.write.settleBatch([oversized]), "BadBatchSize", market);
  });

  it("invariant: N random fees settle with exact provider/treasury/burn totals", async () => {
    const seed = 20260818;
    const rand = rng(seed);
    const N = 25;
    const fees = Array.from({ length: N }, () => BigInt(1 + Math.floor(rand() * 1_000_000)) * (ONE / 1000n));

    // random fees can sum far beyond the beforeEach funding — top up first
    await token.write.transfer([user.account.address, 20_000n * ONE]);
    const userToken = await as("WagiToken", token.address, user);
    const total = fees.reduce((a, b) => a + b, 0n);
    await userToken.write.approve([market.address, total]);

    const batch = fees.map((fee, i) => [
      user.account.address,
      i % 2 === 0 ? providerA.account.address : providerB.account.address,
      "0x" + (0xf000 + i).toString(16).padStart(64, "0"),
      fee,
      1n,
      1n,
    ]);
    await (await relayerMarket()).write.settleBatch([batch]);

    // expected totals computed independently in BigInt
    let providerExpected = 0n;
    let treasuryExpected = 0n;
    let burnExpected = 0n;
    for (const fee of fees) {
      const p = (fee * 8000n) / 10000n;
      const t = (fee * 1500n) / 10000n;
      providerExpected += p;
      treasuryExpected += t;
      burnExpected += fee - p - t;
    }

    expect(await token.read.balanceOf([providerA.account.address]) + await token.read.balanceOf([providerB.account.address]))
      .to.equal(providerExpected);
    expect(await market.read.burnedTotal()).to.equal(burnExpected);
    expect(await market.read.feesTotal()).to.equal(total);
    expect(await token.read.totalSupply()).to.equal(1_000_000_000n * ONE - burnExpected);
    // no dust: everything the contract pulled was redistributed or burned
    expect(await token.read.balanceOf([market.address])).to.equal(0n);
  });
});

describe("Merkle airdrop — randomized trees", () => {
  it("random trees verify every leaf and reject forgeries (seeded)", async () => {
    const seed = 1337421;
    const rand = rng(seed);
    for (let round = 0; round < 5; round++) {
      const size = 1 + Math.floor(rand() * 8);
      const leaves = Array.from({ length: size }, () => makeLeaf("0x" + Math.floor(rand() * 1e12).toString(16).padStart(40, "0"), BigInt(Math.floor(rand() * 1e6))));
      const tree = buildTree(leaves);

      for (const leaf of leaves) {
        expect(verifyProof(tree.getProof(leaf), leaf, tree.root)).to.equal(true);
      }
      // forged leaf must fail
      const forged = makeLeaf("0x" + "de".repeat(20), 999n);
      expect(verifyProof(tree.getProof(leaves[0]), forged, tree.root)).to.equal(false);
    }
  });

  it("on-chain: every leaf of a random tree claims exactly once", async () => {
    const seed = 90210;
    const rand = rng(seed);
    const treasury = await walletClient(0);
    const size = 5;
    const addrs = [];
    for (let i = 0; i < size; i++) addrs.push((await walletClient(i + 1)).account.address);
    const entries = Array.from({ length: size }, (_, i) => ({
      who: addrs[i],
      amount: BigInt(1 + Math.floor(rand() * 1000)) * ONE,
    }));
    const leaves = entries.map((e) => makeLeaf(e.who, e.amount));
    const tree = buildTree(leaves);

    const token = await deploy("WagiToken", [treasury.account.address]);
    const airdrop = await deploy("WagiAirdrop", [token.address, tree.root, BigInt(size)]);
    await token.write.transfer([airdrop.address, entries.reduce((a, e) => a + e.amount, 0n)]);

    for (let i = 0; i < size; i++) {
      const claimer = await as("WagiAirdrop", airdrop.address, await walletClient(i + 1));
      const e = entries[i];
      await claimer.write.claim([e.amount, tree.getProof(makeLeaf(e.who, e.amount))]);
      expect(await token.read.balanceOf([e.who])).to.equal(e.amount);
    }
    // all claimed: one more attempt reverts
    const again = await as("WagiAirdrop", airdrop.address, await walletClient(1));
    await expectRevert(
      () => again.write.claim([entries[0].amount, tree.getProof(makeLeaf(entries[0].who, entries[0].amount))]),
      "AlreadyClaimed",
      airdrop
    );
  });
});
