// Ops helper: drive a WenAGI multisig from the CLI.
//   submit + auto-confirm:  npx hardhat run scripts/exec-via-multisig.js --no-compile -- \
//       --multisig 0x... --dest 0x... --calldata 0x... [--value 0] --artifact InferenceMarket \
//       --fn registerProvider --args '["0xProvider"]'
//   confirm as another owner: rerun with --confirm --tx-id N
//   execute (anyone):         rerun with --execute --tx-id N
//
// The acting account is the first wallet client (DEPLOYER_PRIVATE_KEY on live
// networks) and must be an owner for submit/confirm.
import hre from "hardhat";
import { encodeFunctionData } from "viem";
import { artifact, as } from "../test/helpers.js";

const arg = (name) => {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
};

async function main() {
  const multisig = arg("--multisig");
  if (!multisig) throw new Error("--multisig <address> required");
  const [actor] = await hre.viem.getWalletClients();
  const ms = await as("WagiMultisig", multisig, actor);
  const isOwner = await ms.read.isOwner([actor.account.address]);

  if (arg("--confirm")) {
    if (!isOwner) throw new Error(`actor ${actor.account.address} is not an owner of ${multisig}`);
    const txId = BigInt(arg("--tx-id"));
    await ms.write.confirmTransaction([txId]);
    console.log(`confirmed tx ${txId} — now ${await ms.read.getConfirmationCount([txId])}/${await ms.read.required()}`);
    return;
  }

  if (arg("--execute")) {
    const txId = BigInt(arg("--tx-id"));
    await ms.write.executeTransaction([txId]);
    console.log(`executed tx ${txId}`);
    return;
  }

  const dest = arg("--dest");
  const artName = arg("--artifact");
  const fn = arg("--fn");
  if (!dest || !artName || !fn) throw new Error("--dest, --artifact <ContractName> and --fn required for submit");
  const args = JSON.parse(arg("--args") ?? "[]");
  const value = BigInt(arg("--value") ?? 0);

  const data = encodeFunctionData({ abi: artifact(artName).abi, functionName: fn, args });
  if (!isOwner) throw new Error(`actor ${actor.account.address} is not an owner of ${multisig}`);
  await ms.write.submitTransaction([dest, value, data]);
  const txId = (await ms.read.transactionCount()) - 1n;
  console.log(`submitted tx ${txId}: ${artName}.${fn}(...) → ${dest}`);
  console.log(`calldata: ${data}`);
  console.log(`next: owners confirm (--confirm --tx-id ${txId}), then --execute --tx-id ${txId}`);
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
