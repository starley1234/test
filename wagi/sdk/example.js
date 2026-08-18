// Quick demo: node example.js [gatewayUrl]
// 1) creates a demo key, 2) asks something, 3) shows the burn, 4) leaderboard.
import { connect } from "./index.js";

const baseUrl = process.argv[2] ?? "http://localhost:8080";

const wagi = await connect(baseUrl, { label: "sdk-demo" });
console.log("key created:", wagi.apiKey.slice(0, 14) + "…");

const answer = await wagi.ask("wen agi?");
console.log("\nWAGI-1 says:\n" + answer);

const me = await wagi.me();
console.log(`\n💰 balance ${me.balance} WAGI · 🔥 burned ${me.burned} · prompts ${me.prompts}`);

const stats = await wagi.stats();
console.log(`🌐 AGI progress ${stats.progressPct}% · era "${stats.era.name}" · supply ${stats.supply}`);

const lb = await wagi.leaderboard();
if (lb.items.length) {
  console.log("\n🏆 top burners:");
  lb.items.forEach((e, i) => console.log(`  ${i + 1}. ${e.label} — 🔥${e.burned} WAGI (${e.handle})`));
}
