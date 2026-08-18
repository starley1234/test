import { expect } from "chai";
import { deploy, as, walletClient, expectRevert } from "./helpers.js";

const ONE = 10n ** 18n;

describe("AGIProgressOracle", () => {
  let oracle, owner, oracleAcct;

  beforeEach(async () => {
    owner = await walletClient(0);
    oracleAcct = await walletClient(1);
    oracle = await deploy("AGIProgressOracle", [oracleAcct.account.address]);
  });

  it("starts at 0% in the Chatbots era with 10 eras seeded", async () => {
    expect(Number(await oracle.read.progressBps())).to.equal(0);
    expect(await oracle.read.eraCount()).to.equal(10n);
    expect((await oracle.read.eraAt([0n]))[1]).to.equal("Chatbots");
    expect((await oracle.read.eraAt([9n]))[1]).to.equal("AGI");
  });

  it("eraForBurned walks the thresholds", async () => {
    expect(await oracle.read.eraForBurned([0n])).to.equal(0n);
    expect(await oracle.read.eraForBurned([49_999n * ONE])).to.equal(0n);
    expect(await oracle.read.eraForBurned([50_000n * ONE])).to.equal(1n); // Agents
    expect(await oracle.read.eraForBurned([500_000n * ONE])).to.equal(4n); // Ghost Labor
    expect(await oracle.read.eraForBurned([999_999n * ONE])).to.equal(9n); // AGI
  });

  it("oracle updates progress, others cannot", async () => {
    const oracleC = await as("AGIProgressOracle", oracle.address, oracleAcct);
    await oracleC.write.update([600n, "agents everywhere", 50_000n * ONE]);
    expect(Number(await oracle.read.progressBps())).to.equal(600);

    const snap = await oracle.read.snapshot([50_000n * ONE]);
    expect(Number(snap[0])).to.equal(600); // bps
    expect(snap[1]).to.equal("Agents"); // era implied by burns
    expect(snap[4]).to.equal("agents everywhere"); // narrative
  });

  it("cannot rug the narrative: capped at 100% and max 1% drop per update", async () => {
    const oracleC = await as("AGIProgressOracle", oracle.address, oracleAcct);
    await expectRevert(() => oracleC.write.update([10_001n, "over", 0n]), "TooHigh", oracle);
    await oracleC.write.update([5_000n, "halfway", 0n]);
    await expectRevert(() => oracleC.write.update([4_000n, "dump", 0n]), "TooFarBack", oracle);
    await oracleC.write.update([4_900n, "honest dip", 0n]); // -100 bps allowed
    expect(Number(await oracle.read.progressBps())).to.equal(4_900);
  });
});
