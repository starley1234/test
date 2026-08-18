import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { once } from "node:events";
import { connect, WenAGIClient, WenAGIError } from "../index.js";
import { createApp } from "../../backend/src/server.js";

async function startGateway() {
  const dir = mkdtempSync(join(tmpdir(), "wagi-sdk-"));
  const app = createApp({ stateFile: join(dir, "state.json"), startingBalance: 5, faucetAmount: 1 });
  const server = app.listen(0, "127.0.0.1");
  await once(server, "listening");
  return { server, base: `http://127.0.0.1:${server.address().port}` };
}

test("connect → chat → billing tracked end to end", async () => {
  const { server, base } = await startGateway();
  try {
    const wagi = await connect(base, { label: "sdk-test" });
    assert.match(wagi.apiKey, /^sk-wagi-/);

    const data = await wagi.chat([{ role: "user", content: "wen agi?" }]);
    assert.equal(data.object, "chat.completion");
    assert.ok(data.choices[0].message.content.length > 0);
    assert.ok(wagi.lastBilling.fee >= 0.1);
    assert.ok(wagi.lastBilling.split.burn > 0);

    const text = await wagi.ask("again");
    assert.ok(typeof text === "string" && text.length > 0);

    const me = await wagi.me();
    assert.equal(me.prompts, 2);
    assert.ok(me.burned > 0);
    assert.ok(me.balance < 5);

    const stats = await wagi.stats();
    assert.ok(stats.progressBps >= 0 && Array.isArray(stats.eras));

    const lb = await wagi.leaderboard();
    assert.equal(lb.items[0].label, "sdk-test");
  } finally {
    server.close();
  }
});

test("errors are typed and carry status", async () => {
  const { server, base } = await startGateway();
  try {
    const bad = new WenAGIClient({ baseUrl: base, apiKey: "sk-wagi-deadbeef" });
    await assert.rejects(() => bad.chat([{ role: "user", content: "hi" }]), (e) => {
      assert.ok(e instanceof WenAGIError);
      assert.equal(e.status, 401);
      return true;
    });

    const wagi = new WenAGIClient({ baseUrl: base });
    await assert.rejects(() => wagi.me(), WenAGIError); // no key yet

    await assert.rejects(
      () => wagi.chat([]),
      (e) => e.name === "WenAGIError" && /messages/.test(e.message)
    );
  } finally {
    server.close();
  }
});

test("faucet tops the balance up through the sdk", async () => {
  const { server, base } = await startGateway();
  try {
    const wagi = await connect(base);
    const before = (await wagi.me()).balance;
    const res = await wagi.faucet();
    assert.ok(res.balance > before);
  } finally {
    server.close();
  }
});
