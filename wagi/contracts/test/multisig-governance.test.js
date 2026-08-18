import { expect } from "chai";
import { encodeFunctionData } from "viem";
import { deploy, as, walletClient, expectRevert, artifact } from "./helpers.js";

const ONE = 10n ** 18n;
const FEE = 100n * ONE;

/**
 * Full governance integration:
 *   treasuryMultisig (3/5) — DAO: owns all contracts, receives fee share
 *   relayerMultisig (2/3)  — settles inference on InferenceMarket
 *   oracleMultisig  (2/3)  — updates the AGI progress oracle
 */
async function governanceFixture() {
  const accounts = [];
  for (let i = 0; i < 12; i++) accounts.push(await walletClient(i));

  const mkMultisig = async (ownerIdx, required) => {
    const addrs = ownerIdx.map((i) => accounts[i].account.address);
    const ms = await deploy("WagiMultisig", [addrs, BigInt(required)]);
    const h = await Promise.all(ownerIdx.map((i) => as("WagiMultisig", ms.address, accounts[i])));
    return { ms, h, required };
  };

  const treasury = await mkMultisig([1, 2, 3, 4, 5], 3); // 3/5 DAO
  const relayer = await mkMultisig([6, 7, 8], 2); // 2/3 fast ops
  const oracle = await mkMultisig([9, 10, 11], 2); // 2/3

  const token = await deploy("WagiToken", [treasury.ms.address]);
  const market = await deploy("InferenceMarket", [token.address, treasury.ms.address, relayer.ms.address]);
  const agi = await deploy("AGIProgressOracle", [oracle.ms.address]);

  // governance: contract ownership immediately to the DAO multisig
  await market.write.transferOwnership([treasury.ms.address]);
  await agi.write.transferOwnership([treasury.ms.address]);

  return { accounts, treasury, relayer, oracle, token, market, agi };
}

/** Run an arbitrary contract call through a multisig (submit+confirm+execute). */
async function execViaMultisig(f, target, functionName, args, value = 0n) {
  const data = encodeFunctionData({ abi: artifact(target._name).abi, functionName, args });
  await f.h[0].write.submitTransaction([target.address, value, data]);
  const txId = BigInt(Number(await f.ms.read.transactionCount()) - 1);
  for (let i = 1; i < f.required; i++) await f.h[i].write.confirmTransaction([txId]);
  await f.h[0].write.executeTransaction([txId]);
  return txId;
}

describe("WenAGI under multisig governance", () => {
  it("relayer MULTISIG settles inference: 80/15/5 lands on multisig treasury", async () => {
    const g = await governanceFixture();
    const user = await as("WagiToken", g.token.address, g.accounts[1]);
    const userAddr = g.accounts[1].account.address;
    const provider = g.accounts[2].account.address; // provider stays an EOA (a GPU node)

    // treasury multisig funds the user and registers the provider
    await execViaMultisig(g.treasury, g.token, "transfer", [userAddr, 1000n * ONE]);
    await execViaMultisig(g.treasury, g.market, "registerProvider", [provider]);

    // user approves; the relayer MULTISIG settles the request
    await user.write.approve([g.market.address, FEE]);
    await execViaMultisig(g.relayer, g.market, "settle", [
      userAddr,
      provider,
      "0x" + "99".repeat(32),
      FEE,
      10n,
      20n,
    ]);

    expect(await g.token.read.balanceOf([provider])).to.equal(80n * ONE);
    expect(await g.token.read.balanceOf([g.treasury.ms.address])).to.equal(
      1_000_000_000n * ONE - 1000n * ONE + 15n * ONE
    );
    expect(await g.token.read.totalSupply()).to.equal(1_000_000_000n * ONE - 5n * ONE);
    expect(await g.market.read.burnedTotal()).to.equal(5n * ONE);
  });

  it("a lone relayer key CANNOT settle — only the multisig threshold can", async () => {
    const g = await governanceFixture();
    const userAddr = g.accounts[1].account.address;
    const provider = g.accounts[2].account.address;

    await execViaMultisig(g.treasury, g.token, "transfer", [userAddr, 1000n * ONE]);
    await execViaMultisig(g.treasury, g.market, "registerProvider", [provider]);
    const user = await as("WagiToken", g.token.address, g.accounts[1]);
    await user.write.approve([g.market.address, FEE]);

    // single relayer owner tries directly -> rejected (not the relayer)
    const lone = await as("InferenceMarket", g.market.address, g.accounts[6]);
    await expectRevert(
      () => lone.write.settle([userAddr, provider, "0x" + "aa".repeat(32), FEE, 10n, 20n]),
      "OnlyRelayer",
      g.market
    );

    // one multisig confirmation is NOT enough to execute settle either
    const data = encodeFunctionData({
      abi: artifact("InferenceMarket").abi,
      functionName: "settle",
      args: [userAddr, provider, "0x" + "aa".repeat(32), FEE, 10n, 20n],
    });
    await g.relayer.h[0].write.submitTransaction([g.market.address, 0n, data]);
    const txId = BigInt(Number(await g.relayer.ms.read.transactionCount()) - 1);
    await expectRevert(() => g.relayer.h[1].write.executeTransaction([txId]), "NotEnoughConfirmations", g.relayer.ms);

    // second confirmation unlocks it — execution may be sponsored by anyone
    await g.relayer.h[1].write.confirmTransaction([txId]);
    const sponsor = await as("WagiMultisig", g.relayer.ms.address, g.accounts[0]);
    await sponsor.write.executeTransaction([txId]);
    expect(await g.market.read.settledRequests()).to.equal(1n);
  });

  it("oracle MULTISIG moves the AGI progress needle", async () => {
    const g = await governanceFixture();
    expect(Number(await g.agi.read.progressBps())).to.equal(0);

    await execViaMultisig(g.oracle, g.agi, "update", [750n, "consensus of machines", 42n * ONE]);
    expect(Number(await g.agi.read.progressBps())).to.equal(750);

    // a random account cannot move the needle
    const rando = await as("AGIProgressOracle", g.agi.address, g.accounts[0]);
    await expectRevert(() => rando.write.update([900n, "hijack", 0n]), "OnlyOracle", g.agi);
  });

  it("treasury MULTISIG spends its fee share only by threshold", async () => {
    const g = await governanceFixture();
    const userAddr = g.accounts[1].account.address;
    const provider = g.accounts[2].account.address;
    const payee = g.accounts[9].account.address;

    await execViaMultisig(g.treasury, g.token, "transfer", [userAddr, 1000n * ONE]);
    await execViaMultisig(g.treasury, g.market, "registerProvider", [provider]);
    const user = await as("WagiToken", g.token.address, g.accounts[1]);
    await user.write.approve([g.market.address, FEE]);
    await execViaMultisig(g.relayer, g.market, "settle", [
      userAddr,
      provider,
      "0x" + "bb".repeat(32),
      FEE,
      1n,
      1n,
    ]);

    // DAO balance: 1B - 1000 (funded user) + 15 (treasury share)
    expect(await g.token.read.balanceOf([g.treasury.ms.address])).to.equal(
      1_000_000_000n * ONE - 1000n * ONE + 15n * ONE
    );

    // grant attempt with only 2/3 confirmations is stuck
    const grant = encodeFunctionData({
      abi: artifact("WagiToken").abi,
      functionName: "transfer",
      args: [payee, 5n * ONE],
    });
    await g.treasury.h[0].write.submitTransaction([g.token.address, 0n, grant]);
    const txId = BigInt(Number(await g.treasury.ms.read.transactionCount()) - 1);
    await g.treasury.h[1].write.confirmTransaction([txId]);
    await expectRevert(() => g.treasury.h[0].write.executeTransaction([txId]), "NotEnoughConfirmations", g.treasury.ms);

    // third confirmation releases the grant
    await g.treasury.h[2].write.confirmTransaction([txId]);
    await g.treasury.h[0].write.executeTransaction([txId]);
    expect(await g.token.read.balanceOf([payee])).to.equal(5n * ONE);
  });

  it("contract ownership lives at the DAO multisig from deploy", async () => {
    const g = await governanceFixture();
    const dao = g.treasury.ms.address;
    expect((await g.market.read.owner()).toLowerCase()).to.equal(dao.toLowerCase());
    expect((await g.agi.read.owner()).toLowerCase()).to.equal(dao.toLowerCase());

    // the deployer (EOA) has no power anymore
    await expectRevert(() => g.market.write.setRelayer([g.accounts[1].account.address]), "OnlyOwner", g.market);

    // administration happens only through threshold
    await execViaMultisig(g.treasury, g.market, "registerProvider", [g.accounts[3].account.address]);
    expect(await g.market.read.isProvider([g.accounts[3].account.address])).to.equal(true);
  });
});
