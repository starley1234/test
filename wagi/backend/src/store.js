// Atomic JSON state store — survives restarts, zero dependencies.
import { readFileSync, writeFileSync, renameSync, mkdirSync, existsSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { dirname, join } from "node:path";
import { MAX_SUPPLY } from "./pricing.js";

const DEFAULT_STATE = () => ({
  version: 1,
  burnedTotal: 0, // cumulative WAGI burned (demo ledger mirrors on-chain)
  treasury: 0,
  prompts: 0,
  providers: { "node-alpha": 0, "node-beta": 0 }, // earnings per GPU node
  wall: [], // public anonymized prompt wall
  keys: {}, // apiKey -> { label, balance (WAGI), spent, created, ip }
});

export class Store {
  constructor(file) {
    this.file = file;
    this.state = DEFAULT_STATE();
    mkdirSync(dirname(file), { recursive: true });
    if (existsSync(file)) {
      try {
        const parsed = JSON.parse(readFileSync(file, "utf8"));
        this.state = { ...DEFAULT_STATE(), ...parsed };
      } catch (err) {
        // corrupted state must never take the gateway down
        this.state = DEFAULT_STATE();
      }
    }
    this._flushScheduled = false;
  }

  flush() {
    const tmp = this.file + ".tmp";
    writeFileSync(tmp, JSON.stringify(this.state));
    renameSync(tmp, this.file);
  }

  scheduleFlush() {
    if (this._flushScheduled) return;
    this._flushScheduled = true;
    setTimeout(() => {
      this._flushScheduled = false;
      try {
        this.flush();
      } catch {
        /* keep serving; next write retries */
      }
    }, 250).unref();
  }

  newKey({ label, ip, startingBalance }) {
    const key = "sk-wagi-" + randomBytes(20).toString("hex");
    this.state.keys[key] = {
      label: String(label ?? "anon").slice(0, 48),
      balance: startingBalance,
      spent: 0,
      burned: 0,
      prompts: 0,
      created: Date.now(),
      ip: ip ?? null,
    };
    this.scheduleFlush();
    return key;
  }

  keyInfo(key) {
    return this.state.keys[key] ?? null;
  }

  topUp(key, amount) {
    const info = this.state.keys[key];
    if (!info) return null;
    info.balance += amount;
    this.scheduleFlush();
    return info;
  }

  /// Charge `parts` (from splitFee) to the key; returns remaining balance.
  charge(key, fee, parts) {
    const info = this.state.keys[key];
    if (!info) throw new Error("unknown key");
    if (info.balance < fee) {
      const err = new Error(
        `insufficient $WAGI balance: have ${info.balance.toFixed(3)}, need ${fee.toFixed(3)}. Use the faucet in the playground.`
      );
      err.status = 402;
      throw err;
    }
    info.balance -= fee;
    info.spent += fee;
    info.burned = (info.burned ?? 0) + parts.burn;
    info.prompts = (info.prompts ?? 0) + 1;

    const nodes = Object.keys(this.state.providers);
    const node = nodes[Object.keys(this.state.keys).indexOf(key) % nodes.length];
    this.state.providers[node] += parts.provider;
    this.state.treasury += parts.treasury;
    this.state.burnedTotal += parts.burn;
    this.state.prompts += 1;
    this.scheduleFlush();
    return { balance: info.balance, node };
  }

  pushWall(item) {
    this.state.wall.unshift(item);
    if (this.state.wall.length > 200) this.state.wall.length = 200;
    this.scheduleFlush();
  }

  /// Top burners for the leaderboard (api keys are never exposed).
  leaderboard(limit = 10) {
    return Object.entries(this.state.keys)
      .map(([key, info]) => ({
        key,
        label: info.label,
        burned: round6(info.burned ?? 0),
        spent: round6(info.spent ?? 0),
        prompts: info.prompts ?? 0,
      }))
      .filter((e) => e.burned > 0)
      .sort((a, b) => b.burned - a.burned)
      .slice(0, limit)
      .map(({ key, ...rest }) => ({ ...rest, handle: "…" + key.slice(-6) }));
  }

  stats() {
    return {
      supply: MAX_SUPPLY - this.state.burnedTotal,
      burnedTotal: round6(this.state.burnedTotal),
      treasury: round6(this.state.treasury),
      prompts: this.state.prompts,
      providers: Object.fromEntries(
        Object.entries(this.state.providers).map(([k, v]) => [k, round6(v)])
      ),
      keys: Object.keys(this.state.keys).length,
    };
  }
}

function round6(x) {
  return Math.round(x * 1e6) / 1e6;
}

export function storePathFromEnv(env = process.env) {
  return env.WAGI_STATE_FILE || join(process.cwd(), "data", "state.json");
}
