import { expect } from "chai";
import { deploy, as, walletClient, publicClient, expectRevert, evmNow } from "./helpers.js";

const ONE = 10n ** 18n;

describe("WagiToken", () => {
  let token, treasury, alice, bob;

  beforeEach(async () => {
    treasury = await walletClient(0);
    alice = await walletClient(1);
    bob = await walletClient(2);
    token = await deploy("WagiToken", [treasury.account.address]);
  });

  it("has correct metadata and fixed 1B supply", async () => {
    expect(await token.read.name()).to.equal("WenAGI");
    expect(await token.read.symbol()).to.equal("WAGI");
    expect(Number(await token.read.decimals())).to.equal(18);
    expect(await token.read.totalSupply()).to.equal(1_000_000_000n * ONE);
    expect(await token.read.balanceOf([treasury.account.address])).to.equal(1_000_000_000n * ONE);
  });

  it("transfers and reverts on insufficient balance", async () => {
    await token.write.transfer([alice.account.address, 100n * ONE]);
    expect(await token.read.balanceOf([alice.account.address])).to.equal(100n * ONE);

    const aliceToken = await as("WagiToken", token.address, alice);
    await expectRevert(() => aliceToken.write.transfer([bob.account.address, 101n * ONE]), "InsufficientBalance", token);
  });

  it("approve / transferFrom respects allowance", async () => {
    await token.write.approve([alice.account.address, 10n * ONE]);
    const aliceToken = await as("WagiToken", token.address, alice);
    await aliceToken.write.transferFrom([treasury.account.address, bob.account.address, 7n * ONE]);
    expect(await token.read.allowance([treasury.account.address, alice.account.address])).to.equal(3n * ONE);
    await expectRevert(
      () => aliceToken.write.transferFrom([treasury.account.address, bob.account.address, 4n * ONE]),
      "InsufficientAllowance",
      token
    );
  });

  it("burn reduces balance and total supply", async () => {
    await token.write.burn([5n * ONE]);
    expect(await token.read.totalSupply()).to.equal(1_000_000_000n * ONE - 5n * ONE);
    expect(await token.read.balanceOf([treasury.account.address])).to.equal(1_000_000_000n * ONE - 5n * ONE);
  });

  it("EIP-2612 permit grants allowance via signature and blocks replay", async () => {
    const pc = await publicClient();
    const chainId = await pc.getChainId();
    const deadline = (await evmNow()) + 3600n;
    const value = 42n * ONE;
    const message = {
      owner: alice.account.address,
      spender: bob.account.address,
      value,
      nonce: 0n,
      deadline,
    };
    const domain = { name: "WenAGI", version: "1", chainId, verifyingContract: token.address };
    const types = {
      Permit: [
        { name: "owner", type: "address" },
        { name: "spender", type: "address" },
        { name: "value", type: "uint256" },
        { name: "nonce", type: "uint256" },
        { name: "deadline", type: "uint256" },
      ],
    };

    const signature = await alice.signTypedData({ account: alice.account, domain, types, primaryType: "Permit", message });
    const hex = signature.slice(2);
    const r = "0x" + hex.slice(0, 64);
    const s = "0x" + hex.slice(64, 128);
    const v = BigInt(parseInt(hex.slice(128, 130), 16));

    await token.write.permit([alice.account.address, bob.account.address, value, deadline, v, r, s]);

    expect(await token.read.allowance([alice.account.address, bob.account.address])).to.equal(value);
    expect(await token.read.nonces([alice.account.address])).to.equal(1n);

    await expectRevert(
      () => token.write.permit([alice.account.address, bob.account.address, value, deadline, v, r, s]),
      "PermitInvalidSigner",
      token
    );
  });
});
