// Compile all contracts with solc-js (npm `solc`) into artifacts/*.json.
// Used instead of `hardhat compile` in sandboxed/offline environments where
// binaries.soliditylang.org is unreachable; output format is
// { contractName, abi, bytecode } — consumed by test/helpers.js and CI.
import { readdirSync, readFileSync, writeFileSync, mkdirSync, statSync } from "node:fs";
import { join, dirname, basename, extname } from "node:path";
import { fileURLToPath } from "node:url";
import solc from "solc";

const root = dirname(fileURLToPath(import.meta.url));
const srcDir = join(root, "..", "src");
const outDir = join(root, "..", "artifacts");
mkdirSync(outDir, { recursive: true });

const files = readdirSync(srcDir).filter((f) => extname(f) === ".sol");
const sources = {};
for (const f of files) sources[f] = { content: readFileSync(join(srcDir, f), "utf8") };

const input = {
  language: "Solidity",
  sources,
  settings: {
    optimizer: { enabled: true, runs: 200 },
    evmVersion: "cancun",
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object", "metadata"] } },
  },
};

const output = JSON.parse(solc.compile(JSON.stringify(input)));

let failed = false;
for (const [file, errs] of Object.entries(output.errors ?? {})) void file;
for (const err of output.errors ?? []) {
  if (err.severity === "error") {
    failed = true;
    console.error(`✖ ${err.severity}: ${err.formattedMessage}`);
  } else {
    console.warn(`• ${err.formattedMessage}`);
  }
}
if (failed) process.exit(1);

for (const [file, contracts] of Object.entries(output.contracts)) {
  for (const [name, data] of Object.entries(contracts)) {
    const artifact = {
      contractName: name,
      sourceFile: basename(file),
      abi: data.abi,
      bytecode: "0x" + data.evm.bytecode.object,
      deployedBytecode: "0x" + data.evm.deployedBytecode.object,
      compiler: { version: solc.version() },
    };
    writeFileSync(join(outDir, `${name}.json`), JSON.stringify(artifact, null, 2));
    const kb = (Buffer.byteLength(data.evm.deployedBytecode.object, "utf8") / 2 / 1024).toFixed(2);
    console.log(`✔ ${name} — deployed size ${kb} kB`);
  }
}
