// Build the airdrop merkle tree from a JSON file of { address, amount } entries.
//   echo '[{"address":"0xf39...","amount":"1000000000000000000000"}]' > airdrop.json
//   node scripts/airdrop-tree.js airdrop.json
// Writes airdrop-root.txt (root) and airdrop-proofs.json (per-wallet proofs).
import { readFileSync, writeFileSync } from "node:fs";
import { buildTree, makeLeaf } from "./lib/merkle.js";

const file = process.argv[2];
if (!file) {
  console.error("usage: node scripts/airdrop-tree.js <airdrop.json>");
  process.exit(1);
}

const entries = JSON.parse(readFileSync(file, "utf8"));
const leaves = entries.map((e) => makeLeaf(e.address, BigInt(e.amount)));
const tree = buildTree(leaves);

writeFileSync("airdrop-root.txt", tree.root + "\n");
const proofs = {};
entries.forEach((e, i) => {
  proofs[e.address] = { amount: e.amount, proof: tree.getProof(leaves[i]) };
});
writeFileSync("airdrop-proofs.json", JSON.stringify(proofs, null, 2));

console.log("leaves:", leaves.length);
console.log("root:  ", tree.root);
console.log("wrote airdrop-root.txt, airdrop-proofs.json");
