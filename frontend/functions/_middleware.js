// Password gate for the whole hosted site (Cloudflare Pages). Every page, data file and API
// call passes through here. Secrets live in the Pages project settings, never in the code:
// SITE_PASSWORD and SESSION_SECRET.
const COOKIE = "eqd_session";
const MAX_AGE = 30 * 24 * 3600;
const enc = new TextEncoder();

async function sign(secret, message) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(message)));
  return btoa(String.fromCharCode(...sig)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function same(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function cookies(header) {
  const out = {};
  for (const part of (header || "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

function loginPage(message, status) {
  const html = `<!doctype html><html lang="en-IN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in, Equity desk</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f3f5f8;color:#172033;font:16px/1.5 system-ui,sans-serif}
form{background:#fff;border:1px solid #d9dee6;border-radius:10px;padding:2rem;width:min(22rem,calc(100vw - 2rem))}
h1{font-size:1.25rem;margin:0 0 1rem}label{display:block;margin-bottom:.4rem;color:#5b6475}
input{width:100%;box-sizing:border-box;font:inherit;padding:.55rem .8rem;border:1px solid #b9c1cd;border-radius:6px}
button{margin-top:1rem;width:100%;font:inherit;font-weight:600;background:#2f3b9c;color:#fff;border:0;border-radius:6px;padding:.6rem}
p{color:#b43c2e;margin:.75rem 0 0}</style></head><body>
<form method="post" action="/login"><h1>Equity desk</h1><label for="pw">Password</label>
<input id="pw" name="password" type="password" autocomplete="current-password" autofocus required>
<button type="submit">Sign in</button>${message ? `<p role="alert">${message}</p>` : ""}</form></body></html>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

export async function onRequest({ request, env, next }) {
  if (!env.SITE_PASSWORD || !env.SESSION_SECRET) return new Response("Site is not configured", { status: 503 });
  const url = new URL(request.url);

  if (url.pathname === "/login" && request.method === "POST") {
    const form = await request.formData();
    if (same(String(form.get("password") || ""), env.SITE_PASSWORD)) {
      const exp = String(Math.floor(Date.now() / 1000) + MAX_AGE);
      const token = `${exp}.${await sign(env.SESSION_SECRET, exp)}`;
      return new Response(null, {
        status: 303,
        headers: { Location: "/", "Set-Cookie": `${COOKIE}=${token}; Path=/; Max-Age=${MAX_AGE}; HttpOnly; Secure; SameSite=Lax` },
      });
    }
    await new Promise((r) => setTimeout(r, 1000)); // slow down guessing
    return loginPage("Wrong password.", 401);
  }

  const value = cookies(request.headers.get("Cookie"))[COOKIE];
  if (value) {
    const [exp, sig] = value.split(".");
    if (Number(exp) > Date.now() / 1000 && same(sig || "", await sign(env.SESSION_SECRET, exp))) {
      const res = await next();
      if (url.pathname.startsWith("/data/")) {
        const copy = new Response(res.body, res);
        copy.headers.set("cache-control", "private, no-cache"); // updated daily; never shared caches
        return copy;
      }
      return res;
    }
  }
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/data/")) {
    return new Response(JSON.stringify({ detail: "Sign in first" }), { status: 401, headers: { "content-type": "application/json" } });
  }
  return loginPage("", 200);
}
