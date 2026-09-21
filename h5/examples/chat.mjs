// Server-side Node.js 20+ example. Never bundle API keys into a browser application.
const { PLATFORM_BASE_URL: base, PLATFORM_API_KEY: key, PLATFORM_MODEL: model } = process.env;
if (!base || !key || !model) {
  throw new Error("Set PLATFORM_BASE_URL, PLATFORM_API_KEY and PLATFORM_MODEL.");
}
const url = new URL(base);
const localHttp = url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname);
if (url.username || url.password || url.search || url.hash ||
    !["/v1", "/v1/"].includes(url.pathname) || (url.protocol !== "https:" && !localHttp)) {
  throw new Error("Use a trusted HTTPS base ending in /v1; HTTP is allowed only for loopback development.");
}

const response = await fetch(`${url.href.replace(/\/$/, "")}/chat/completions`, {
  method: "POST",
  redirect: "error",
  signal: AbortSignal.timeout(60_000),
  headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
  body: JSON.stringify({
    model,
    messages: [{ role: "user", content: "Hello" }],
    max_tokens: 128,
  }),
}).catch(() => {
  throw new Error("Connection failed or timed out; outcome is unknown. Check usage before retrying.");
});
if (!response.ok) {
  throw new Error(`HTTP ${response.status}: check permissions, limits and usage before retrying.`);
}
const result = await response.json();
const text = result.choices?.[0]?.message?.content;
if (typeof text !== "string") {
  throw new Error("No text completion returned; inspect the model protocol and usage record.");
}
console.log(text);
