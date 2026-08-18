// WenAGI Gateway — OpenAI-compatible inference paid in $WAGI.
// Zero runtime dependencies; Node >= 18.
import { createServer } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { Store, storePathFromEnv } from "./store.js";
import {
  feeFor,
  splitFee,
  progressBpsFor,
  eraForBurned,
  estimateTokens,
  PRICING,
  ERAS,
} from "./pricing.js";
import { completeMock, completeReal } from "./engine.js";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
};

const REDACT_EMAIL = /[\w.+-]+@[\w-]+\.[\w.]+/gi;
const REDACT_PHONE = /(\+?\d[\d\s().-]{7,}\d)/g;

function sanitizeForWall(text, limit = 110) {
  return String(text ?? "")
    .replace(REDACT_EMAIL, "[email]")
    .replace(REDACT_PHONE, "[phone]")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
}

export function createApp(options = {}) {
  const store = options.store ?? new Store(options.stateFile ?? storePathFromEnv());
  const publicDir = options.publicDir ?? join(import.meta.dirname, "..", "public");
  const startingBalance = options.startingBalance ?? 1000;
  const faucetAmount = options.faucetAmount ?? 250;
  const chatRpm = options.chatRpm ?? 30; // per-key requests per minute
  const upstream = options.upstream ?? null; // { base, apiKey, model }

  const ipBuckets = new Map(); // ip -> { count, resetAt }
  function rateLimit(ip, max = 12, windowMs = 60_000) {
    const now = Date.now();
    const b = ipBuckets.get(ip) ?? { count: 0, resetAt: now + windowMs };
    if (now > b.resetAt) {
      b.count = 0;
      b.resetAt = now + windowMs;
    }
    b.count += 1;
    ipBuckets.set(ip, b);
    return b.count <= max;
  }

  function json(res, code, body) {
    const payload = JSON.stringify(body);
    res.writeHead(code, {
      "content-type": "application/json",
      "cache-control": "no-store",
      "access-control-allow-origin": options.corsOrigin ?? "*",
    });
    res.end(payload);
  }

  async function readBody(req, limit = 1 << 20) {
    let size = 0;
    const chunks = [];
    for await (const chunk of req) {
      size += chunk.length;
      if (size > limit) throw Object.assign(new Error("body too large"), { status: 413 });
      chunks.push(chunk);
    }
    if (!chunks.length) return {};
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  }

  function serveStatic(req, res, url) {
    let path = url.pathname === "/" ? "/index.html" : url.pathname;
    const file = normalize(join(publicDir, path));
    if (!file.startsWith(publicDir) || !existsSync(file) || !statSync(file).isFile()) {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("not found");
      return;
    }
    res.writeHead(200, {
      "content-type": MIME[extname(file)] ?? "application/octet-stream",
      "cache-control": "public, max-age=120",
    });
    createReadStream(file).pipe(res);
  }

  const server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://localhost");
    try {
      // CORS preflight
      if (req.method === "OPTIONS") {
        res.writeHead(204, {
          "access-control-allow-origin": options.corsOrigin ?? "*",
          "access-control-allow-methods": "GET,POST,OPTIONS",
          "access-control-allow-headers": "authorization,content-type",
        });
        return res.end();
      }

      if (req.method === "GET" && url.pathname === "/healthz") {
        return json(res, 200, { ok: true, uptime: process.uptime() });
      }

      if (req.method === "GET" && url.pathname === "/api/stats") {
        const s = store.stats();
        const bps = progressBpsFor(s.burnedTotal);
        const era = eraForBurned(s.burnedTotal);
        return json(res, 200, {
          ...s,
          maxSupply: 1_000_000_000,
          progressBps: bps,
          progressPct: Math.round((bps / 100) * 10) / 10,
          era: { name: era.name, quip: era.quip },
          pricing: PRICING,
          eras: ERAS.map((e) => ({ burned: e.burned, name: e.name, quip: e.quip })),
        });
      }

      if (req.method === "GET" && url.pathname === "/api/wall") {
        return json(res, 200, { items: store.state.wall.slice(0, 30) });
      }

      if (req.method === "GET" && url.pathname === "/api/leaderboard") {
        return json(res, 200, { items: store.leaderboard(10) });
      }

      if (req.method === "GET" && url.pathname === "/api/me") {
        const auth = (req.headers.authorization ?? "").replace(/^Bearer\s+/i, "");
        const info = store.keyInfo(auth);
        if (!info) return json(res, 401, { error: "invalid api key" });
        return json(res, 200, {
          label: info.label,
          balance: Math.round(info.balance * 1e6) / 1e6,
          spent: Math.round(info.spent * 1e6) / 1e6,
          burned: Math.round((info.burned ?? 0) * 1e6) / 1e6,
          prompts: info.prompts ?? 0,
        });
      }

      if (req.method === "POST" && url.pathname === "/api/keys") {
        const ip = req.socket.remoteAddress ?? "?";
        if (!rateLimit("key:" + ip)) return json(res, 429, { error: "too many keys requested, slow down" });
        const body = await readBody(req).catch(() => ({}));
        const key = store.newKey({ label: body.label, ip, startingBalance });
        return json(res, 201, { apiKey: key, balance: startingBalance, note: "demo credits, not real $WAGI" });
      }

      if (req.method === "POST" && url.pathname === "/api/faucet") {
        const auth = (req.headers.authorization ?? "").replace(/^Bearer\s+/i, "");
        const info = store.keyInfo(auth);
        if (!info) return json(res, 404, { error: "unknown api key — create one at /api/keys" });
        const ip = req.socket.remoteAddress ?? "?";
        if (!rateLimit("faucet:" + ip, 5)) return json(res, 429, { error: "faucet cooldown" });
        store.topUp(auth, faucetAmount);
        return json(res, 200, { balance: info.balance, toppedUp: faucetAmount });
      }

      if (req.method === "GET" && url.pathname === "/v1/models") {
        return json(res, 200, {
          object: "list",
          data: [
            { id: "wagi-1", object: "model", owned_by: "wenagi", pricing: PRICING },
            ...(upstream ? [{ id: "real/" + upstream.model, object: "model", owned_by: "upstream" }] : []),
          ],
        });
      }

      if (req.method === "POST" && url.pathname === "/v1/chat/completions") {
        const auth = (req.headers.authorization ?? "").replace(/^Bearer\s+/i, "");
        const info = store.keyInfo(auth);
        if (!info) return json(res, 401, { error: "invalid api key (create one: POST /api/keys)" });
        if (!rateLimit("chat:" + auth, chatRpm, 60_000)) {
          return json(res, 429, { error: `rate limit: ${chatRpm} requests/minute per key` });
        }
        const body = await readBody(req);
        const messages = Array.isArray(body.messages) ? body.messages : null;
        if (!messages?.length) return json(res, 400, { error: "messages[] required" });

        const model = String(body.model ?? "wagi-1");
        const wantReal = model.startsWith("real/") && upstream;

        let result;
        try {
          result = wantReal
            ? await completeReal({
                model,
                messages,
                temperature: body.temperature,
                max_tokens: body.max_tokens,
                base: upstream.base,
                apiKey: upstream.apiKey,
                upstreamModel: model.replace(/^real\//, "") || upstream.model,
              })
            : await completeMock({ model, messages, temperature: body.temperature });
        } catch (e) {
          return json(res, 502, { error: "upstream failure", detail: String(e.message).slice(0, 200) });
        }

        const tokensIn = body.stream ? result.tokensIn : result.tokensIn;
        const fee = feeFor(result.tokensIn, result.tokensOut);
        const parts = splitFee(fee);

        let chargeResult;
        try {
          chargeResult = store.charge(auth, fee, parts);
        } catch (e) {
          return json(res, e.status ?? 500, { error: e.message });
        }

        const lastUserMsg = [...messages].reverse().find((m) => m.role === "user")?.content ?? "";
        store.pushWall({
          q: sanitizeForWall(lastUserMsg),
          model,
          ts: Date.now(),
          burned: parts.burn,
          node: chargeResult.node,
        });

        return json(res, 200, {
          id: "chatcmpl-wagi-" + randomUUID().slice(0, 8),
          object: "chat.completion",
          created: Math.floor(Date.now() / 1000),
          model,
          choices: [
            {
              index: 0,
              message: { role: "assistant", content: result.content },
              finish_reason: "stop",
            },
          ],
          usage: {
            prompt_tokens: result.tokensIn,
            completion_tokens: result.tokensOut,
            total_tokens: result.tokensIn + result.tokensOut,
          },
          wagi: {
            fee,
            split: parts,
            balance: chargeResult.balance,
            burnedTotal: Math.round(store.state.burnedTotal * 1e6) / 1e6,
            progressBps: progressBpsFor(store.state.burnedTotal),
          },
        });
      }

      if (req.method === "GET") {
        return serveStatic(req, res, url);
      }

      return json(res, 405, { error: "method not allowed" });
    } catch (e) {
      return json(res, e.status ?? 500, { error: String(e.message ?? e) });
    }
  });

  server.store = store;
  return server;
}
