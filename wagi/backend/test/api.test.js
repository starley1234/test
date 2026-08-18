import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { once } from "node:events";
import { createApp } from "../src/server.js";

async function startServer() {
  const dir = mkdtempSync(join(tmpdir(), "wagi-test-"));
  const app = createApp({ stateFile: join(dir, "state.json"), startingBalance: 5, faucetAmount: 1 });
  const server = app.listen(0, "127.0.0.1");
  await once(server, "listening");
  const base = `http://127.0.0.1:${server.address().port}`;
  return { server, base, app };
}

test("health + stats + models endpoints", async () => {
  const { server, base } = await startServer();
  try {
    const health = await (await fetch(base + "/healthz")).json();
    assert.equal(health.ok, true);

    const stats = await (await fetch(base + "/api/stats")).json();
    assert.equal(stats.maxSupply, 1_000_000_000);
    assert.ok(Array.isArray(stats.eras) && stats.eras.length === 10);
    assert.equal(stats.era.name, "Chatbots");

    const models = await (await fetch(base + "/v1/models")).json();
    assert.equal(models.data[0].id, "wagi-1");
  } finally {
    server.close();
  }
});

test("full chat flow: key -> completion -> billing -> wall -> stats", async () => {
  const { server, base, app } = await startServer();
  try {
    const keyRes = await fetch(base + "/api/keys", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ label: "test" }),
    });
    assert.equal(keyRes.status, 201);
    const { apiKey } = await keyRes.json();

    // unauthorized is rejected
    const unauth = await fetch(base + "/v1/chat/completions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages: [{ role: "user", content: "hi" }] }),
    });
    assert.equal(unauth.status, 401);

    // completion is OpenAI-shaped and billed
    const chat = await fetch(base + "/v1/chat/completions", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer " + apiKey },
      body: JSON.stringify({ model: "wagi-1", messages: [{ role: "user", content: "wen agi?" }] }),
    });
    assert.equal(chat.status, 200);
    const data = await chat.json();
    assert.equal(data.object, "chat.completion");
    assert.ok(data.choices[0].message.content.length > 10);
    assert.ok(data.usage.total_tokens > 0);
    assert.ok(data.wagi.fee >= 0.1);
    assert.ok(data.wagi.split.burn > 0);
    assert.ok(data.wagi.balance < 5);

    // prompt landed on the public wall, sanitized
    const wall = await (await fetch(base + "/api/wall")).json();
    assert.equal(wall.items.length, 1);
    assert.ok(wall.items[0].q.length <= 110);

    // stats moved
    const stats = await (await fetch(base + "/api/stats")).json();
    assert.equal(stats.prompts, 1);
    assert.ok(stats.burnedTotal > 0);
    assert.ok(stats.supply < 1_000_000_000);

    // spending everything then requesting more -> 402 payment required
    const burner = app.store.keyInfo(apiKey);
    app.store.topUp(apiKey, -burner.balance + 0.05); // leave dust
    const broke = await fetch(base + "/v1/chat/completions", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer " + apiKey },
      body: JSON.stringify({ messages: [{ role: "user", content: "again" }] }),
    });
    assert.equal(broke.status, 402);
    assert.ok((await broke.json()).error.includes("insufficient"));

    // faucet tops up
    const faucet = await fetch(base + "/api/faucet", {
      method: "POST",
      headers: { authorization: "Bearer " + apiKey },
    });
    assert.equal(faucet.status, 200);
    assert.ok((await faucet.json()).balance > 0);
  } finally {
    server.close();
  }
});

test("/api/me reflects billing, leaderboard ranks burners", async () => {
  const { server, base } = await startServer();
  try {
    const { apiKey: big } = await (
      await fetch(base + "/api/keys", { method: "POST", body: JSON.stringify({ label: "big-burner" }), headers: { "content-type": "application/json" } })
    ).json();
    const { apiKey: small } = await (
      await fetch(base + "/api/keys", { method: "POST", body: JSON.stringify({ label: "tiny" }), headers: { "content-type": "application/json" } })
    ).json();

    const chat = (key) =>
      fetch(base + "/v1/chat/completions", {
        method: "POST",
        headers: { "content-type": "application/json", authorization: "Bearer " + key },
        body: JSON.stringify({ messages: [{ role: "user", content: "burn some wagi please, a long prompt to raise the fee above the floor" }] }),
      });

    await chat(big); await chat(big); await chat(small);

    const me = await (await fetch(base + "/api/me", { headers: { authorization: "Bearer " + big } })).json();
    assert.ok(me.burned > 0 && me.prompts === 2 && me.balance < 5);
    const unauth = await fetch(base + "/api/me");
    assert.equal(unauth.status, 401);

    const lb = await (await fetch(base + "/api/leaderboard")).json();
    assert.equal(lb.items.length, 2);
    assert.equal(lb.items[0].label, "big-burner"); // burned more, ranked first
    assert.ok(lb.items[0].burned >= lb.items[1].burned);
    assert.ok(!JSON.stringify(lb).includes("sk-wagi-"), "api keys must never leak");
  } finally {
    server.close();
  }
});

test("per-key rate limiting returns 429 beyond the budget", async () => {
  const dir = mkdtempSync(join(tmpdir(), "wagi-rl-"));
  const app = createApp({ stateFile: join(dir, "state.json"), chatRpm: 3 });
  const server = app.listen(0, "127.0.0.1");
  await once(server, "listening");
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const { apiKey } = await (
      await fetch(base + "/api/keys", { method: "POST", body: "{}", headers: { "content-type": "application/json" } })
    ).json();
    const send = () =>
      fetch(base + "/v1/chat/completions", {
        method: "POST",
        headers: { "content-type": "application/json", authorization: "Bearer " + apiKey },
        body: JSON.stringify({ messages: [{ role: "user", content: "wen?" }] }),
      });
    const codes = [];
    for (let i = 0; i < 5; i++) codes.push((await send()).status);
    assert.deepEqual(codes.slice(0, 3), [200, 200, 200]);
    assert.equal(codes[3], 429);
    assert.equal(codes[4], 429);
  } finally {
    server.close();
  }
});

test("wall sanitizes emails and phones", async () => {
  const { server, base } = await startServer();
  try {
    const { apiKey } = await (
      await fetch(base + "/api/keys", { method: "POST", body: "{}", headers: { "content-type": "application/json" } })
    ).json();
    await fetch(base + "/v1/chat/completions", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer " + apiKey },
      body: JSON.stringify({
        messages: [{ role: "user", content: "mail me at agent@gmail.com or call +7 999 123 45 67" }],
      }),
    });
    const wall = await (await fetch(base + "/api/wall")).json();
    assert.ok(!wall.items[0].q.includes("agent@gmail.com"), "email leaked to wall");
    assert.ok(wall.items[0].q.includes("[email]"));
  } finally {
    server.close();
  }
});
