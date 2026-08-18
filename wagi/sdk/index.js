// @wenagi/sdk — zero-dependency client for the WenAGI Gateway.
// Drop-in for agents that want OpenAI-shaped chat billed in $WAGI.
//
//   import { connect } from "@wenagi/sdk";
//   const wagi = await connect("http://localhost:8080", { label: "my-agent" });
//   const res = await wagi.chat([{ role: "user", content: "wen agi?" }]);
//   console.log(res.choices[0].message.content, wagi.lastBilling);

export class WenAGIError extends Error {
  constructor(message, { status, body } = {}) {
    super(message);
    this.name = "WenAGIError";
    this.status = status;
    this.body = body;
  }
}

export class WenAGIClient {
  /**
   * @param {object} opts
   * @param {string} opts.baseUrl  gateway origin, e.g. https://gateway.wenagi.ai
   * @param {string} [opts.apiKey] existing sk-wagi-… key (or call createKey)
   * @param {typeof fetch} [opts.fetchImpl] injectable fetch (tests, edge runtimes)
   */
  constructor({ baseUrl, apiKey, fetchImpl } = {}) {
    if (!baseUrl) throw new Error("baseUrl required");
    this.baseUrl = String(baseUrl).replace(/\/+$/, "");
    this.apiKey = apiKey ?? null;
    this.fetch = fetchImpl ?? globalThis.fetch?.bind(globalThis);
    if (!this.fetch) throw new Error("no fetch available — pass fetchImpl");
    this.lastBilling = null; // { fee, split, balance, burnedTotal, progressBps }
  }

  authHeaders() {
    if (!this.apiKey) throw new WenAGIError("no api key — call createKey() or pass one", { status: 401 });
    return { authorization: "Bearer " + this.apiKey };
  }

  async _json(path, { method = "GET", body, auth = false } = {}) {
    const headers = { "content-type": "application/json" };
    if (auth) Object.assign(headers, this.authHeaders());
    const res = await this.fetch(this.baseUrl + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try {
      data = await res.json();
    } catch {
      /* non-JSON error page */
    }
    if (!res.ok) {
      throw new WenAGIError(data?.error ?? `HTTP ${res.status}`, { status: res.status, body: data });
    }
    return data;
  }

  /** Create a fresh demo key (demo credits) and adopt it. */
  async createKey(label = "agent") {
    const data = await this._json("/api/keys", { method: "POST", body: { label } });
    this.apiKey = data.apiKey;
    return data;
  }

  /**
   * OpenAI-compatible chat completion.
   * @param {Array<{role:string,content:string}>} messages
   * @param {object} [opts] { model, temperature, maxTokens }
   * @returns {Promise<object>} OpenAI-shaped response + `wagi` billing block
   */
  async chat(messages, { model = "wagi-1", temperature, maxTokens } = {}) {
    if (!Array.isArray(messages) || !messages.length) {
      throw new WenAGIError("messages[] required");
    }
    const data = await this._json("/v1/chat/completions", {
      method: "POST",
      auth: true,
      body: {
        model,
        messages,
        ...(temperature !== undefined ? { temperature } : {}),
        ...(maxTokens !== undefined ? { max_tokens: maxTokens } : {}),
      },
    });
    this.lastBilling = data.wagi ?? null;
    return data;
  }

  /** Convenience: just the assistant text. */
  async ask(content, opts) {
    const data = await this.chat([{ role: "user", content }], opts);
    return data.choices[0].message.content;
  }

  /** Current key balance / spend / burn stats. */
  async me() {
    return this._json("/api/me", { auth: true });
  }

  /** Top up demo credits. */
  async faucet() {
    return this._json("/api/faucet", { method: "POST", auth: true });
  }

  /** Network stats: supply, burned, AGI progress. */
  async stats() {
    return this._json("/api/stats");
  }

  /** Top burners of the network. */
  async leaderboard() {
    return this._json("/api/leaderboard");
  }
}

/** Connect and create a key in one call. */
export async function connect(baseUrl, { label = "agent", apiKey } = {}) {
  const client = new WenAGIClient({ baseUrl, apiKey });
  if (!apiKey) await client.createKey(label);
  return client;
}
