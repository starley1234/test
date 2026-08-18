#!/usr/bin/env node
// Entry point: WAGI Gateway. Env:
//   PORT=8080  WAGI_STATE_FILE=data/state.json
//   OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL — enable real-model proxy
//   STARTING_BALANCE=1000  FAUCET_AMOUNT=250
import { createApp } from "./src/server.js";

const port = Number(process.env.PORT ?? 8080);
const upstream = process.env.OPENAI_API_KEY
  ? {
      base: process.env.OPENAI_BASE_URL ?? "https://api.openai.com/v1",
      apiKey: process.env.OPENAI_API_KEY,
      model: process.env.OPENAI_MODEL ?? "gpt-4o-mini",
    }
  : null;

const app = createApp({
  upstream,
  startingBalance: Number(process.env.STARTING_BALANCE ?? 1000),
  faucetAmount: Number(process.env.FAUCET_AMOUNT ?? 250),
});

app.listen(port, "0.0.0.0", () => {
  console.log(`[wagi-gateway] listening on :${port}`);
  console.log(`[wagi-gateway] demo model wagi-1 ready${upstream ? `, upstream model real/${upstream.model} ready` : ""}`);
});
