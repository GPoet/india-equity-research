// Research on the hosted site. GET returns the latest stored result; POST starts a GitHub
// Actions job (research.yml) that runs Claude with the subscription token and writes the result
// back to the RESEARCH KV namespace. Settings: GH_TOKEN (fine-grained, Actions: write on GH_REPO
// only), GH_REPO ("owner/name"); KV binding RESEARCH.
const SYMBOL = /^[A-Z0-9&_-]{1,24}$/;
const RUNNING_TTL = 20 * 60;
// No sign-in on this site, so cap research runs per day: each one uses the owner's Claude plan.
const DEFAULT_DAILY_CAP = 20;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
}

function symbolOf(params) {
  const sym = decodeURIComponent(String(params.symbol || "")).toUpperCase();
  return SYMBOL.test(sym) ? sym : null;
}

export async function onRequestGet({ params, env }) {
  const sym = symbolOf(params);
  if (!sym) return json({ detail: "Unknown symbol" }, 400);
  const stored = await env.RESEARCH.get(`r-${sym}`, "json");
  if (stored && stored.status === "done") return json({ status: "done", data: stored.data, cached: true });
  if (await env.RESEARCH.get(`p-${sym}`)) return json({ status: "running" });
  return json(stored || { status: "none" });
}

export async function onRequestPost({ params, env, request }) {
  const url = new URL(request.url);
  const origin = request.headers.get("Origin");
  if (request.headers.get("X-Equity-Desk") !== "1" || (origin && new URL(origin).host !== url.host)) {
    return json({ detail: "Cross-site request refused" }, 403);
  }
  const sym = symbolOf(params);
  if (!sym) return json({ detail: "Unknown symbol" }, 400);
  if (sym.startsWith("BSE-")) {
    return json({ status: "failed", error: "Research covers NSE-listed companies for now", kind: "unsupported" });
  }
  if (await env.RESEARCH.get(`p-${sym}`)) return json({ status: "running" });
  const day = new Date().toISOString().slice(0, 10);
  const used = Number((await env.RESEARCH.get(`n-${day}`)) || 0);
  const cap = Number(env.RESEARCH_DAILY_CAP || DEFAULT_DAILY_CAP);
  if (used >= cap) {
    return json({ status: "failed", error: `Daily research limit reached (${cap} runs); try again tomorrow`, kind: "rate_limit" });
  }
  const res = await fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/research.yml/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "equity-desk",
    },
    body: JSON.stringify({ ref: "main", inputs: { symbol: sym } }),
  });
  if (!res.ok) return json({ status: "failed", error: `Could not start research (GitHub HTTP ${res.status})`, kind: "upstream" });
  await env.RESEARCH.put(`p-${sym}`, String(Date.now()), { expirationTtl: RUNNING_TTL });
  await env.RESEARCH.put(`n-${day}`, String(used + 1), { expirationTtl: 3 * 24 * 3600 });
  return json({ status: "queued" });
}
