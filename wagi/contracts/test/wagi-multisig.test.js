import { expect } from "chai";
import { encodeFunctionData, parseEther } from "viem";
import { deploy, as, walletClient, expectRevert, publicClient, artifact } from "./helpers.js";

const ONE = 10n ** 18n;

/** Deploy a 3-of-5 multisig over accounts 1..5; h[i] is owner i's handle. */
async function multisigFixture({ required = 3n, ownerIdx = [1, 2, 3, 4, 5] } = {}) {
  const owners = [];
  for (const i of ownerIdx) owners.push(await walletClient(i));
  const addrs = owners.map((o) => o.account.address);
  const ms = await deploy("WagiMultisig", [addrs, required]);
  const h = await Promise.all(owners.map((o) => as("WagiMultisig", ms.address, o)));
  return { ms, owners, addrs, h };
}

describe("WagiMultisig — unit", () => {
  it("deploys with owners, threshold and zero transactions", async () => {
    const { ms, addrs } = await multisigFixture();
    const stranger = await walletClient(9);
    expect(Number(await ms.read.required())).to.equal(3);
    expect(Number(await ms.read.ownerCount())).to.equal(5);
    expect(Number(await ms.read.transactionCount())).to.equal(0);
    const got = (await ms.read.getOwners()).map((a) => a.toLowerCase());
    expect(got).to.deep.equal(addrs.map((a) => a.toLowerCase()));
    expect(await ms.read.isOwner([addrs[0]])).to.equal(true);
    expect(await ms.read.isOwner([stranger.account.address])).to.equal(false);
  });

  it("rejects bad configurations at deploy", async () => {
    const a = (await walletClient(1)).account.address;
    const b = (await walletClient(2)).account.address;
    // constructor reverts surface as raw deployment failures: assert rejection
    const rejects = async (args) => {
      try {
        await deploy("WagiMultisig", args);
      } catch {
        return; // rejected — as expected
      }
      throw new Error("expected deploy to revert, but it succeeded");
    };
    await rejects([[], 1n]); // empty owner set
    await rejects([[a, "0x" + "0".repeat(40)], 1n]); // zero address
    await rejects([[a, a], 1n]); // duplicate owner
    await rejects([[a, b], 0n]); // zero threshold
    await rejects([[a, b], 3n]); // threshold above owner count
  });

  it("submission is owner-only; submitter is auto-confirmed", async () => {
    const { ms, h, owners } = await multisigFixture();
    const outsider = await as("WagiMultisig", ms.address, await walletClient(9));
    await expectRevert(
      () => outsider.write.submitTransaction([owners[0].account.address, 0n, "0x"]),
      "NotOwner",
      ms
    );

    await h[0].write.submitTransaction([owners[0].account.address, 0n, "0x"]);
    expect(Number(await ms.read.transactionCount())).to.equal(1);
    expect(Number(await ms.read.getConfirmationCount([0n]))).to.equal(1);
  });

  it("executes only after the threshold is reached — then anyone can execute", async () => {
    const { ms, h, owners } = await multisigFixture();
    const token = await deploy("WagiToken", [owners[0].account.address]);
    const treasuryToken = await as("WagiToken", token.address, owners[0]);
    const recipient = (await walletClient(9)).account.address;
    await treasuryToken.write.transfer([ms.address, 100n * ONE]);

    const data = encodeFunctionData({
      abi: artifact("WagiToken").abi,
      functionName: "transfer",
      args: [recipient, 10n * ONE],
    });
    await h[0].write.submitTransaction([token.address, 0n, data]);
    await h[1].write.confirmTransaction([0n]);

    // 2 of 3 confirmations: not enough — for an owner and for a stranger
    await expectRevert(() => h[0].write.executeTransaction([0n]), "NotEnoughConfirmations", ms);
    const stranger = await as("WagiMultisig", ms.address, await walletClient(9));
    await expectRevert(() => stranger.write.executeTransaction([0n]), "NotEnoughConfirmations", ms);

    await h[2].write.confirmTransaction([0n]); // 3 of 3
    await stranger.write.executeTransaction([0n]); // anyone may broadcast
    expect(await token.read.balanceOf([recipient])).to.equal(10n * ONE);
    expect((await ms.read.getTransaction([0n]))[3]).to.equal(true); // executed
  });

  it("blocks double confirmation, allows revoke, and updates counts", async () => {
    const { ms, h, owners } = await multisigFixture();
    await h[0].write.submitTransaction([owners[4].account.address, 0n, "0x"]);

    await expectRevert(() => h[0].write.confirmTransaction([0n]), "AlreadyConfirmed", ms);
    await h[1].write.confirmTransaction([0n]);
    await h[2].write.confirmTransaction([0n]);
    expect(Number(await ms.read.getConfirmationCount([0n]))).to.equal(3);

    await h[2].write.revokeConfirmation([0n]);
    expect(Number(await ms.read.getConfirmationCount([0n]))).to.equal(2);

    await expectRevert(() => h[3].write.revokeConfirmation([0n]), "NotConfirmed", ms);
    await h[2].write.confirmTransaction([0n]); // back to 3
    await h[0].write.executeTransaction([0n]);
  });

  it("cannot execute twice and cannot touch unknown tx ids", async () => {
    const { ms, h, owners } = await multisigFixture();
    await expectRevert(() => h[0].write.confirmTransaction([7n]), "TxNotFound", ms);
    await h[0].write.submitTransaction([owners[1].account.address, 0n, "0x"]);
    await h[1].write.confirmTransaction([0n]);
    await h[2].write.confirmTransaction([0n]);
    await h[0].write.executeTransaction([0n]);
    await expectRevert(() => h[0].write.executeTransaction([0n]), "TxAlreadyExecuted", ms);
  });

  it("failed calls revert and leave the transaction retryable", async () => {
    const { ms, h, owners } = await multisigFixture();
    const token = await deploy("WagiToken", [owners[0].account.address]);
    const treasuryToken = await as("WagiToken", token.address, owners[0]);
    const recipient = (await walletClient(9)).account.address;
    // multisig holds NO tokens -> transfer must fail
    const data = encodeFunctionData({
      abi: artifact("WagiToken").abi,
      functionName: "transfer",
      args: [recipient, 10n * ONE],
    });
    await h[0].write.submitTransaction([token.address, 0n, data]);
    await h[1].write.confirmTransaction([0n]);
    await h[2].write.confirmTransaction([0n]);

    await expectRevert(() => h[0].write.executeTransaction([0n]), "CallFailed", ms);
    expect((await ms.read.getTransaction([0n]))[3]).to.equal(false); // still pending

    // fund and retry the same txId
    await treasuryToken.write.transfer([ms.address, 100n * ONE]);
    await h[0].write.executeTransaction([0n]);
    expect(await token.read.balanceOf([recipient])).to.equal(10n * ONE);
  });

  it("holds and sends ETH via confirmed transactions", async () => {
    const { ms, h, owners } = await multisigFixture();
    const funder = await walletClient(0);
    const beneficiary = (await walletClient(9)).account.address;
    await funder.sendTransaction({ to: ms.address, value: parseEther("1") });

    const pc = await publicClient();
    const before = await pc.getBalance({ address: beneficiary });
    await h[0].write.submitTransaction([beneficiary, parseEther("0.4"), "0x"]);
    await h[1].write.confirmTransaction([0n]);
    await h[2].write.confirmTransaction([0n]);
    await h[0].write.executeTransaction([0n]);
    const after = await pc.getBalance({ address: beneficiary });
    expect(after - before).to.equal(parseEther("0.4"));
    void owners;
  });
});

describe("WagiMultisig — wallet administration (self-calls)", () => {
  async function selfCall(fn, args, f) {
    const data = encodeFunctionData({ abi: artifact("WagiMultisig").abi, functionName: fn, args });
    await f.h[0].write.submitTransaction([f.ms.address, 0n, data]);
    const txId = BigInt(Number(await f.ms.read.transactionCount()) - 1);
    // confirm with owners 1..3 — enough for any threshold used in these tests
    for (let i = 1; i <= 3; i++) await f.h[i].write.confirmTransaction([txId]);
    await f.h[0].write.executeTransaction([txId]);
    return txId;
  }

  it("changes threshold through a confirmed self-call", async () => {
    const f = await multisigFixture();
    expect(Number(await f.ms.read.required())).to.equal(3);
    await selfCall("changeThreshold", [4n], f);
    expect(Number(await f.ms.read.required())).to.equal(4);

    // a fresh tx now needs 4 confirmations
    await f.h[0].write.submitTransaction([f.owners[4].account.address, 0n, "0x"]);
    await f.h[1].write.confirmTransaction([1n]);
    await f.h[2].write.confirmTransaction([1n]);
    await expectRevert(() => f.h[0].write.executeTransaction([1n]), "NotEnoughConfirmations", f.ms);
    await f.h[3].write.confirmTransaction([1n]);
    await f.h[0].write.executeTransaction([1n]);
  });

  it("replaces and adds owners through self-calls", async () => {
    const f = await multisigFixture();
    const newOwner = await walletClient(6);
    await selfCall("replaceOwner", [f.addrs[4], newOwner.account.address], f);
    expect(await f.ms.read.isOwner([f.addrs[4]])).to.equal(false);
    expect(await f.ms.read.isOwner([newOwner.account.address])).to.equal(true);
    expect(Number(await f.ms.read.ownerCount())).to.equal(5);

    const extra = await walletClient(7);
    await selfCall("addOwner", [extra.account.address], f);
    expect(Number(await f.ms.read.ownerCount())).to.equal(6);
  });

  it("removeOwner refuses to drop below the threshold", async () => {
    const f = await multisigFixture();
    // 5 owners / 3 required: removing one leaves 4 >= 3 -> ok
    await selfCall("removeOwner", [f.addrs[4]], f);
    expect(Number(await f.ms.read.ownerCount())).to.equal(4);

    // raise threshold to 4: removing would leave 3 < 4 -> execution fails
    await selfCall("changeThreshold", [4n], f);
    await expectRevert(() => selfCall("removeOwner", [f.addrs[3]], f), "CallFailed", f.ms);
    expect(Number(await f.ms.read.ownerCount())).to.equal(4);
  });

  it("admin functions are unreachable by direct calls", async () => {
    const f = await multisigFixture();
    await expectRevert(() => f.ms.write.changeThreshold([2n]), "NotSelf", f.ms);
    await expectRevert(() => f.ms.write.addOwner([f.addrs[0]]), "NotSelf", f.ms);
  });
});
