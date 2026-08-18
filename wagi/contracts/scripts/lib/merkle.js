// Shared merkle helpers for the WenAGI airdrop (leaf = keccak(keccak(addr, amount))).
import { encodeAbiParameters, keccak256, concat } from "viem";

export function makeLeaf(address, amount) {
  // matches Solidity: keccak256(bytes.concat(keccak256(abi.encode(addr, amount))))
  return keccak256(
    keccak256(encodeAbiParameters([{ type: "address" }, { type: "uint256" }], [address, BigInt(amount)]))
  );
}

function hashPair(a, b) {
  return keccak256(concat(a < b ? [a, b] : [b, a]));
}

/// Minimal, allocation-friendly binary merkle tree over sorted-unique leaves.
export function buildTree(leaves) {
  const unique = [...new Set(leaves)].sort();
  if (unique.length === 0) throw new Error("empty tree");
  let level = unique;
  let padded = false;
  if (level.length === 1) {
    // single-leaf tree: duplicate it so the root is a real hash pair
    level = [level[0], level[0]];
    padded = true;
  }
  const levels = [level];
  while (level.length > 1) {
    const next = [];
    for (let i = 0; i < level.length; i += 2) {
      next.push(i + 1 < level.length ? hashPair(level[i], level[i + 1]) : hashPair(level[i], level[i]));
    }
    level = next;
    levels.push(level);
  }
  const root = level[0];
  const getProof = (leaf) => {
    const idx = levels[0].indexOf(leaf);
    if (idx === -1) throw new Error("leaf not in tree");
    let proof = [];
    let i = idx;
    for (let l = 0; l < levels.length - 1; l++) {
      const lvl = levels[l];
      const sibling = i % 2 === 0 ? (i + 1 < lvl.length ? lvl[i + 1] : lvl[i]) : lvl[i - 1];
      proof.push(sibling);
      i = Math.floor(i / 2);
    }
    return proof;
  };
  return { root, getProof, padded };
}

export function verifyProof(proof, leaf, root) {
  let computed = leaf;
  for (const p of proof) computed = hashPair(computed, p);
  return computed === root;
}
