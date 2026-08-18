import { expect } from "chai";
import { deploy, as, walletClient, warp, expectRevert, evmNow } from "./helpers.js";
import { buildTree, makeLeaf, verifyProof } from "../scripts/lib/merkle.js";

const ONE = 10n ** 18n;

describe("WagiAirdrop", () => {
  let token, airdrop, treasury, alice, bob, mallory, tree;

  beforeEach(async () => {
    treasury = await walletClient(0);
    alice = await walletClient(1);
    bob = await walletClient(2);
    mallory = await walletClient(3);

    const entries = [
      { who: alice.account.address, amount: 100n * ONE },
      { who: bob.account.address, amount: 50n * ONE },
      { who: "0x000000000000000000000000000000000000dEaD", amount: 25n * ONE },
    ];
    tree = buildTree(entries.map((e) => makeLeaf(e.who, e.amount)));

    token = await deploy("WagiToken", [treasury.account.address]);
    airdrop = await deploy("WagiAirdrop", [token.address, tree.root, 3n]);
    await token.write.transfer([airdrop.address, 175n * ONE]);
  });

  it("distributor helper produces a verifiable tree", () => {
    const leaf = makeLeaf(alice.account.address, 100n * ONE);
    const proof = tree.getProof(leaf);
    expect(verifyProof(proof, leaf, tree.root)).to.be.true;
  });

  it("winners claim once, then never again", async () => {
    const aliceDrop = await as("WagiAirdrop", airdrop.address, alice);
    const proof = tree.getProof(makeLeaf(alice.account.address, 100n * ONE));
    await aliceDrop.write.claim([100n * ONE, proof]);
    expect(await token.read.balanceOf([alice.account.address])).to.equal(100n * ONE);

    await expectRevert(() => aliceDrop.write.claim([100n * ONE, proof]), "AlreadyClaimed", airdrop);
  });

  it("rejects forged amounts and proofs", async () => {
    const malloryDrop = await as("WagiAirdrop", airdrop.address, mallory);
    const realProof = tree.getProof(makeLeaf(alice.account.address, 100n * ONE));
    await expectRevert(() => malloryDrop.write.claim([100n * ONE, realProof]), "InvalidProof", airdrop);
    await expectRevert(() => malloryDrop.write.claim([999n * ONE, realProof]), "InvalidProof", airdrop);
  });

  it("owner can recover unclaimed after the window", async () => {
    await airdrop.write.recover([treasury.account.address, 1n * ONE]);
    expect(await token.read.balanceOf([treasury.account.address])).to.equal(
      1_000_000_000n * ONE - 175n * ONE + 1n * ONE
    );
  });
});

describe("TokenVesting", () => {
  let token, vesting, treasury, dev;
  const TOTAL = 100n * ONE;
  const MONTH = 30n * 24n * 60n * 60n;

  beforeEach(async () => {
    treasury = await walletClient(0);
    dev = await walletClient(1);
    token = await deploy("WagiToken", [treasury.account.address]);
    vesting = await deploy("TokenVesting", [token.address]);
    await token.write.transfer([vesting.address, TOTAL]);
  });

  it("nothing vests before the cliff, then linearly to 100%", async () => {
    const start = (await evmNow()) + 1n;
    await vesting.write.create([dev.account.address, TOTAL, start, 6n * MONTH, 24n * MONTH, false]);

    expect(await vesting.read.vested([dev.account.address])).to.equal(0n);

    await warp(6n * MONTH + 1n); // cliff passed, ~25% elapsed
    expect(await vesting.read.vested([dev.account.address])).to.be.closeTo(TOTAL / 4n, TOTAL / 100n);

    await warp(18n * MONTH);
    expect(await vesting.read.vested([dev.account.address])).to.equal(TOTAL);
  });

  it("beneficiary releases in tranches and cannot overdraw", async () => {
    const start = (await evmNow()) + 1n;
    await vesting.write.create([dev.account.address, TOTAL, start, 6n * MONTH, 24n * MONTH, false]);
    const devVest = await as("TokenVesting", vesting.address, dev);

    await expectRevert(() => devVest.write.release(), "NothingToRelease", vesting);

    await warp(12n * MONTH);
    await devVest.write.release();
    expect(await token.read.balanceOf([dev.account.address])).to.be.closeTo(TOTAL / 2n, TOTAL / 100n);

    await warp(12n * MONTH);
    await devVest.write.release();
    expect(await token.read.balanceOf([dev.account.address])).to.equal(TOTAL);
  });

  it("revocation refunds the unvested part, vested stays claimable", async () => {
    const start = (await evmNow()) + 1n;
    await vesting.write.create([dev.account.address, TOTAL, start, 0n, 24n * MONTH, true]);
    await warp(12n * MONTH);

    const before = await token.read.balanceOf([treasury.account.address]);
    await vesting.write.revoke([dev.account.address]);
    const after = await token.read.balanceOf([treasury.account.address]);
    expect(after - before).to.be.closeTo(TOTAL / 2n, TOTAL / 100n);

    const devVest = await as("TokenVesting", vesting.address, dev);
    await devVest.write.release();
    expect(await token.read.balanceOf([dev.account.address])).to.be.closeTo(TOTAL / 2n, TOTAL / 100n);

    await warp(12n * MONTH); // no further vesting after revoke
    await expectRevert(() => devVest.write.release(), "NothingToRelease", vesting);
  });
});
