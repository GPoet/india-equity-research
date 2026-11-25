"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type SentimentState } from "@/lib/api";

const POLL_MS = 4000;

function tone(stance: string): string {
  if (stance === "bullish") return "good";
  if (stance === "bearish") return "bad";
  if (stance === "mixed" || stance === "neutral") return "mid";
  return "plain";
}

// What X (Twitter) is saying, via Grok. Off until an xAI key is in backend/.env.
export function SentimentPanel({ symbol }: { symbol: string }) {
  const [state, setState] = useState<SentimentState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    api.sentiment(symbol).then(
      (s) => {
        if (!live) return;
        setState(s);
        if (s.status === "running" || s.status === "queued") timer = setTimeout(() => setTick((t) => t + 1), POLL_MS);
      },
      (e) => live && setError(e instanceof ApiError ? e.message : "Could not load X sentiment"),
    );
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [symbol, tick]);

  async function start(force: boolean) {
    setBusy(true);
    setError(null);
    try {
      setState(await api.startSentiment(symbol, force));
      setTick((t) => t + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel" aria-live="polite">
      <h2>What X is saying</h2>
      {error && <p className="error">{error}</p>}
      {state?.status === "disabled" && <p className="small muted">{state.error}.</p>}
      {(state?.status === "none" || state?.status === "failed") && (
        <>
          {state.status === "failed" && <p className="error small">{state.error}</p>}
          <p className="small muted" style={{ marginBottom: "0.75rem" }}>
            Grok searches the last 30 days of posts. Costs a few US cents per check, within your monthly cap.
          </p>
          <button className="primary" onClick={() => start(state.status === "failed")} disabled={busy}>
            {busy ? "Starting…" : "Check X sentiment"}
          </button>
        </>
      )}
      {state?.status === "queued" && <p className="small muted">Waiting for another check to finish.</p>}
      {state?.status === "running" && <p className="small muted">Searching X…</p>}
      {state?.status === "done" && (() => {
        const r = state.data.report;
        const m = state.data.meta;
        return (
          <>
            <p>
              <span className={`tag ${tone(r.overall)}`}>{r.overall}</span>{" "}
              <span className="small muted">score {r.score > 0 ? `+${r.score}` : r.score} of ±2, volume {r.volume}</span>
            </p>
            <p className="small" style={{ marginTop: "0.5rem" }}>{r.summary}</p>
            {r.pump_risk.level !== "low" && (
              <p className={`small ${r.pump_risk.level === "high" ? "error" : ""}`} style={{ marginTop: "0.5rem" }}>
                Pump risk {r.pump_risk.level}: {r.pump_risk.signals.join("; ")}
              </p>
            )}
            {r.themes.length > 0 && (
              <ul className="related">
                {r.themes.map((t, i) => (
                  <li key={`${i}-${t.theme}`}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
                      <span>{t.theme}</span>
                      <span className={`tag ${tone(t.stance)}`}>{t.stance}</span>
                    </div>
                    <div className="why">{t.detail}</div>
                  </li>
                ))}
              </ul>
            )}
            {r.notable_posts.length > 0 && (
              <details style={{ marginTop: "0.75rem" }}>
                <summary>Posts quoted ({r.notable_posts.length})</summary>
                <ul className="small">
                  {r.notable_posts.map((p, i) => (
                    <li key={`${i}-${p.url}`}>
                      <a href={p.url} target="_blank" rel="noreferrer noopener">@{p.author}</a> ({p.author_type}, {p.stance}): {p.summary}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <p className="small muted" style={{ marginTop: "0.75rem" }}>
              {m.as_of}, {m.posts_fetched} posts read, cost ${m.cost_usd.toFixed(2)}
              {m.month_spend_usd !== undefined && <>, ${m.month_spend_usd.toFixed(2)} spent this month</>}.{" "}
              <button className="link" onClick={() => start(true)} disabled={busy}>Check again</button>
            </p>
          </>
        );
      })()}
    </div>
  );
}
