// Test helpers: deploy from artifacts/*.json via plain viem on a Hardhat
// in-process network connection (no Hardhat artifact/build step required).
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getContract, keccak256, toBytes } from "viem";
import hre from "hardhat";

const here = dirname(fileURLToPath(import.meta.url));

export function artifact(name) {
  return JSON.parse(readFileSync(join(here, "..", "artifacts", `${name}.json`), "utf8"));
}

let _conn;
/** Shared in-process Hardhat network connection (Hardhat 3 style). */
export async function connection() {
  if (!_conn) _conn = await hre.network.getOrCreate();
  return _conn;
}

/** Current EVM block timestamp (tests must never rely on wall clock). */
export async function evmNow() {
  const pc = await publicClient();
  const block = await pc.getBlock();
  return block.timestamp;
}

let _publicClient;
export async function publicClient() {
  if (!_publicClient) _publicClient = (await connection()).viem.getPublicClient();
  return _publicClient;
}

export async function walletClient(i = 0) {
  const accounts = await (await connection()).viem.getWalletClients();
  return accounts[i];
}

/// Bind a viem contract instance to a specific wallet.
export async function as(name, address, walletClient) {
  const art = artifact(name);
  const contract = getContract({
    address,
    abi: art.abi,
    client: { public: await publicClient(), wallet: walletClient },
  });
  contract.address = address;
  contract._name = name;
  return contract;
}

/// Deploy `name` with constructor `args`, bound to `from` (default: account 0).
export async function deploy(name, args = [], { from } = {}) {
  const art = artifact(name);
  const wc = from ?? (await walletClient(0));
  const pc = await publicClient();
  const hash = await wc.deployContract({
    abi: art.abi,
    bytecode: art.bytecode,
    args,
    account: wc.account,
    chain: null,
  });
  const receipt = await pc.waitForTransactionReceipt({ hash });
  if (!receipt.contractAddress) throw new Error(`deploy of ${name}: no contractAddress`);
  return as(name, receipt.contractAddress, wc);
}

/// Fetch contract events from a mined receipt.
export async function eventsOf(contract, eventName, receipt) {
  const pc = await publicClient();
  return pc.getContractEvents({
    address: contract.address,
    abi: artifact(contract._name).abi,
    eventName,
    fromBlock: receipt.blockNumber,
    toBlock: receipt.blockNumber,
  });
}

/// Advance the Hardhat EVM clock.
export async function warp(seconds) {
  const c = await connection();
  await c.provider.send("evm_increaseTime", [Number(seconds)]);
  await c.provider.send("evm_mine");
}

/// Lightweight custom-error matcher (no chai-matchers plugin needed).
/// Usage: await expectRevert(() => token.write.burn([1n]), "InsufficientBalance")
export async function expectRevert(thunk, errName) {
  try {
    await thunk();
  } catch (e) {
    const blob = [
      e?.shortMessage ?? "",
      e?.details ?? "",
      e?.message ?? "",
      ...(e?.metaMessages ?? []),
      e?.cause?.shortMessage ?? "",
      e?.cause?.details ?? "",
    ].join("\n");
    const normalized = blob.replace(/\s+/g, " ");
    if (normalized.includes(`Error: ${errName}(`) || normalized.includes(`${errName}(`)) return;
    throw new Error(`expected revert with ${errName}, got: ${e?.message}`);
  }
  throw new Error(`expected revert with ${errName}, but the call succeeded`);
}
