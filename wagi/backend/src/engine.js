// WAGI-1 — the built-in demo model. Deterministic, charming, offline.
// When OPENAI_API_KEY is set, requests with model "real/*" are proxied to the
// configured OpenAI-compatible upstream instead (pay-per-use still in $WAGI).

const HOOKS = [
  "processed by a tired GPU somewhere",
  "verified by three llamas in a trench coat",
  "rendered at 3:47 AM local node time",
  "as prophesied in the whitepaper, section 'wen'",
  "funded by burned $WAGI",
];

function hash32(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

function lastUser(messages) {
  for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "user") return messages[i].content;
  return "";
}

export async function completeMock({ model, messages, temperature }) {
  const q = String(lastUser(messages) ?? "");
  const h = hash32(q + "|" + (temperature ?? 1));
  const hook = HOOKS[h % HOOKS.length];
  const short = q.length > 120 ? q.slice(0, 117) + "…" : q;

  const reply = [
    `WAGI-1 here — ${hook}.`,
    ``,
    `You asked: "${short}"`,
    ``,
    `Here is my honest answer: the path to AGI is measured in burned $WAGI, and you just moved the needle. Every prompt you send burns a slice of supply, forever. That's not a bug, that's the flywheel.`,
    ``,
    `Practical part: this endpoint is OpenAI-compatible. Point your existing agent at /v1/chat/completions with an API key from the playground, and your AI pays for itself in $WAGI — 80% to GPU providers, 15% to the treasury, 5% burned for progress.`,
    ``,
    h % 2 === 0
      ? `Estimated AGI arrival: ${new Date(Date.now() + (h % 900) * 86400000).toISOString().slice(0, 10)}. Give or take a decade.`
      : `I ran the numbers ${1 + (h % 42)} times. The numbers say: keep prompting.`,
  ].join("\n");

  return {
    content: reply,
    tokensIn: Math.max(1, Math.ceil((JSON.stringify(messages).length + q.length) / 4)),
    tokensOut: Math.ceil(reply.length / 4),
  };
}

/// Proxy to a real OpenAI-compatible upstream (set OPENAI_API_KEY + OPENAI_BASE_URL).
export async function completeReal({ model, messages, temperature, max_tokens, base, apiKey, upstreamModel }) {
  const res = await fetch(`${base.replace(/\/$/, "")}/chat/completions`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model: upstreamModel,
      messages,
      temperature,
      max_tokens,
    }),
  });
  if (!res.ok) {
    throw new Error(`upstream ${res.status}: ${await res.text()}`);
  }
  const data = await res.json();
  const choice = data.choices?.[0]?.message ?? { content: "(empty)" };
  return {
    content: choice.content ?? "(empty)",
    tokensIn: data.usage?.prompt_tokens ?? Math.ceil(JSON.stringify(messages).length / 4),
    tokensOut: data.usage?.completion_tokens ?? Math.ceil(String(choice.content).length / 4),
  };
}
