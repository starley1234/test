// Deploys the full WenAGI suite WITH multisig governance. Usage:
//   npx hardhat run scripts/deploy.js --no-compile --network baseSepolia
//
// Governance layout (no EOA holds a privileged role after this script):
//   TreasuryMultisig 3/5 — DAO: owns every contract, receives fee share
//   RelayerMultisig  2/3 — settles inference batches (fast ops threshold)
//   OracleMultisig   2/3 — moves the AGI progress needle
//
// Env:
//   DEPLOYER_PRIVATE_KEY            funded deployer (deploys + hands over)
//   MULTISIG_OWNERS_TREASURY=0x..,0x..,0x..,0x..,0x..   (5 owners, comma-separated)
//   MULTISIG_REQUIRED_TREASURY=3
//   MULTISIG_OWNERS_RELAYER / MULTISIG_REQUIRED_RELAYER  (default 2 of 3)
//   MULTISIG_OWNERS_ORACLE  / MULTISIG_REQUIRED_ORACLE   (default 2 of 3)
// On the local hardhat network, owner slots fall back to test accounts —
// NEVER use that fallback on a live network (the script refuses to continue
// without explicit owner env vars there).
import { deploy, walletClient, connection } from "../test/helpers.js";
import hre from "hardhat";

const parseOwners = (name) =>
  (process.env[name] ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

async function main() {
  const network = hre.network?.name ?? "hardhat";
  const isLive = network !== "hardhat" && network !== "localhost";
  const { viem } = await connection();
  const [deployer, ...spare] = await viem.getWalletClients();
  console.log("network:", network);
  console.log("deployer:", deployer.account.address);

  // local fallback: spread owner roles across deterministic test accounts
  const localAddr = async (i) => (await walletClient(i)).account.address;
  const treasuryOwners = parseOwners("MULTISIG_OWNERS_TREASURY");
  const relayerOwners = parseOwners("MULTISIG_OWNERS_RELAYER");
  const oracleOwners = parseOwners("MULTISIG_OWNERS_ORACLE");

  if (isLive && (!treasuryOwners.length || !relayerOwners.length || !oracleOwners.length)) {
    throw new Error(
      "live network requires MULTISIG_OWNERS_TREASURY / _RELAYER / _ORACLE (comma-separated addresses)"
    );
  }

  const tOwners = treasuryOwners.length
    ? treasuryOwners
    : [await localAddr(1), await localAddr(2), await localAddr(3), await localAddr(4), await localAddr(5)];
  const rOwners = relayerOwners.length ? relayerOwners : [await localAddr(6), await localAddr(7), await localAddr(8)];
  const oOwners = oracleOwners.length ? oracleOwners : [await localAddr(9), await localAddr(10), await localAddr(11)];

  const tReq = BigInt(process.env.MULTISIG_REQUIRED_TREASURY ?? 3);
  const rReq = BigInt(process.env.MULTISIG_REQUIRED_RELAYER ?? 2);
  const oReq = BigInt(process.env.MULTISIG_REQUIRED_ORACLE ?? 2);

  console.log("\n── multisig governance ──");
  const treasuryMS = await deploy("WagiMultisig", [tOwners, tReq]);
  console.log(`TreasuryMultisig (${tReq}/${tOwners.length}):`, treasuryMS.address);
  if (!treasuryOwners.length) console.log("  ⚠ local test accounts as owners — DO NOT use on mainnet");
  const relayerMS = await deploy("WagiMultisig", [rOwners, rReq]);
  console.log(`RelayerMultisig  (${rReq}/${rOwners.length}):`, relayerMS.address);
  if (!relayerOwners.length) console.log("  ⚠ local test accounts as owners — DO NOT use on mainnet");
  const oracleMS = await deploy("WagiMultisig", [oOwners, oReq]);
  console.log(`OracleMultisig   (${oReq}/${oOwners.length}):`, oracleMS.address);
  if (!oracleOwners.length) console.log("  ⚠ local test accounts as owners — DO NOT use on mainnet");

  console.log("\n── core suite (privileges to multisigs only) ──");
  const token = await deploy("WagiToken", [treasuryMS.address]);
  console.log("WagiToken:        ", token.address, "→ supply mints to TreasuryMultisig");

  const market = await deploy("InferenceMarket", [token.address, treasuryMS.address, relayerMS.address]);
  console.log("InferenceMarket:  ", market.address, "→ treasury=TreasuryMultisig, relayer=RelayerMultisig");

  const agi = await deploy("AGIProgressOracle", [oracleMS.address]);
  console.log("AGIProgressOracle:", agi.address, "→ oracle=OracleMultisig");

  const vesting = await deploy("TokenVesting", [token.address]);
  const airdrop = await deploy("WagiAirdrop", [token.address, "0x" + "0".repeat(64), 0n]);

  console.log("\n── hand contract ownership to the DAO multisig ──");
  await market.write.transferOwnership([treasuryMS.address]);
  await agi.write.transferOwnership([treasuryMS.address]);
  await vesting.write.transferOwnership([treasuryMS.address]);
  await airdrop.write.transferOwnership([treasuryMS.address]);
  console.log("TokenVesting:     ", vesting.address, "→ owner = TreasuryMultisig");
  console.log("WagiAirdrop:      ", airdrop.address, "→ owner = TreasuryMultisig");
  console.log("InferenceMarket + AGIProgressOracle owner → TreasuryMultisig");

  console.log(`
next steps (see ../docs/PRODUCTION.md):
  1) fund distribution: TreasuryMultisig.submit/confirm/execute token.transfer(...)
     (use scripts/exec-via-multisig.js or the multisig UI)
  2) register GPU providers: market.registerProvider(...) via TreasuryMultisig
  3) airdrop root: node scripts/airdrop-tree.js airdrop.json → setRoot() via TreasuryMultisig
  4) verify sources on Basescan (solc 0.8.28, optimizer 200), update ../backend/.env`);
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
