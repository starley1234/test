import { expect } from "chai";
import { deploy, as, walletClient, eventsOf, publicClient, expectRevert } from "./helpers.js";

const ONE = 10n ** 18n;
const FEE = 100n * ONE;

describe("InferenceMarket", () => {
  let token, market, treasury, relayer, user, provider;

  beforeEach(async () => {
    treasury = await walletClient(0);
    relayer = await walletClient(1);
    user = await walletClient(2);
    provider = await walletClient(3);

    token = await deploy("WagiToken", [treasury.account.address]);
    market = await deploy("InferenceMarket", [
      token.address,
      treasury.account.address,
      relayer.account.address,
    ]);

    await token.write.transfer([user.account.address, 1000n * ONE]);
    await market.write.registerProvider([provider.account.address]);
  });

  async function settleAsRelayer(args) {
    const relayerMarket = await as("InferenceMarket", market.address, relayer);
    return relayerMarket.write.settle(args);
  }

  it("splits the fee 80/15/5 and burns the burn share", async () => {
    const userToken = await as("WagiToken", token.address, user);
    await userToken.write.approve([market.address, FEE]);

    const promptHash = "0x" + "11".repeat(32);
    await settleAsRelayer([user.account.address, provider.account.address, promptHash, FEE, 120n, 340n]);

    expect(await token.read.balanceOf([provider.account.address])).to.equal(80n * ONE);
    expect(await token.read.balanceOf([treasury.account.address])).to.equal(
      1_000_000_000n * ONE - 1000n * ONE + 15n * ONE
    );
    expect(await token.read.totalSupply()).to.equal(1_000_000_000n * ONE - 5n * ONE);
    expect(await market.read.burnedTotal()).to.equal(5n * ONE);
    expect(await market.read.settledRequests()).to.equal(1n);
    expect(await market.read.feesTotal()).to.equal(FEE);
  });

  it("emits PromptSettled with exact parts", async () => {
    const userToken = await as("WagiToken", token.address, user);
    await userToken.write.approve([market.address, FEE]);
    const promptHash = "0x" + "22".repeat(32);
    const hash = await settleAsRelayer([
      user.account.address,
      provider.account.address,
      promptHash,
      FEE,
      1n,
      2n,
    ]);
    const pc = await publicClient();
    const receipt = await pc.waitForTransactionReceipt({ hash });
    const logs = await eventsOf(market, "PromptSettled", receipt);
    expect(logs).to.have.length(1);
    const ev = logs[0].args;
    expect(ev.user.toLowerCase()).to.equal(user.account.address.toLowerCase());
    expect(ev.promptHash).to.equal(promptHash);
    expect(ev.fee).to.equal(FEE);
    expect(ev.providerPart).to.equal(80n * ONE);
    expect(ev.treasuryPart).to.equal(15n * ONE);
    expect(ev.burnPart).to.equal(5n * ONE);
  });

  it("blocks replay of the same prompt hash", async () => {
    const userToken = await as("WagiToken", token.address, user);
    await userToken.write.approve([market.address, 2n * FEE]);
    const promptHash = "0x" + "33".repeat(32);
    await settleAsRelayer([user.account.address, provider.account.address, promptHash, FEE, 1n, 1n]);
    await expectRevert(
      () => settleAsRelayer([user.account.address, provider.account.address, promptHash, FEE, 1n, 1n]),
      "PromptAlreadySettled", market
    );
  });

  it("only the relayer can settle", async () => {
    await token.write.approve([market.address, FEE]);
    const promptHash = "0x" + "44".repeat(32);
    await expectRevert(
      () => market.write.settle([user.account.address, provider.account.address, promptHash, FEE, 1n, 1n]),
      "OnlyRelayer",
      market
    );
  });

  it("rejects unknown providers and bad fee splits", async () => {
    const anyone = await walletClient(4);
    const promptHash = "0x" + "55".repeat(32);
    await expectRevert(
      () => settleAsRelayer([user.account.address, anyone.account.address, promptHash, FEE, 1n, 1n]),
      "UnknownProvider", market
    );

    await expectRevert(() => market.write.setFeeSplit([8000n, 1999n, 1n]), "BadSplit", market);
    await expectRevert(() => market.write.setFeeSplit([9999n, 1n, 0n]), "BadSplit", market);
    await market.write.setFeeSplit([7000n, 2500n, 500n]);
    expect(await market.read.providerBps()).to.equal(7000n);
  });
});
