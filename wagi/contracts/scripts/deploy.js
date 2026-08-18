// Deploys the full WenAGI suite. Usage:
//   npx hardhat run scripts/deploy.js --no-compile --network baseSepolia
//
// Env:
//   DEPLOYER_PRIVATE_KEY  funded deployer key (required for live networks)
//   TREASURY_ADDRESS / RELAYER_ADDRESS / ORACLE_ADDRESS  (multisigs in prod)
// Prints every address — paste into ../backend/.env and the frontend config.
import { deploy } from "../test/helpers.js";
import hre from "hardhat";

async function main() {
  const [deployer] = await hre.viem.getWalletClients();
  console.log("deployer:", deployer.account.address);

  const treasury = process.env.TREASURY_ADDRESS || deployer.account.address;
  const relayer = process.env.RELAYER_ADDRESS || deployer.account.address;
  const oracle = process.env.ORACLE_ADDRESS || deployer.account.address;

  const token = await deploy("WagiToken", [treasury]);
  console.log("WagiToken:        ", token.address);

  const market = await deploy("InferenceMarket", [token.address, treasury, relayer]);
  console.log("InferenceMarket:  ", market.address);

  const agi = await deploy("AGIProgressOracle", [oracle]);
  console.log("AGIProgressOracle:", agi.address);

  const vesting = await deploy("TokenVesting", [token.address]);
  console.log("TokenVesting:     ", vesting.address);

  // Empty root by default — run scripts/airdrop-tree.js, then setRoot().
  const airdrop = await deploy("WagiAirdrop", [token.address, "0x" + "0".repeat(64), 0n]);
  console.log("WagiAirdrop:      ", airdrop.address);

  console.log("\nnext steps:");
  console.log("  1) register providers: market.registerProvider(gpuProvider)");
  console.log("  2) airdrop root: node scripts/airdrop-tree.js airdrop.json && setRoot()");
  console.log("  3) verify sources on Basescan, update ../backend/.env");
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
