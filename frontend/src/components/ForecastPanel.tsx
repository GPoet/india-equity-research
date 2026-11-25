"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type Forecast, type HorizonForecast } from "@/lib/api";
import { pct, rupees } from "@/lib/format";

const LABEL: Record<string, string> = { "1m": "1 month", "2m": "2 months" };

function leanTone(lean: string): string {
  if (lean === "lean buy") return "good";
  if (lean === "lean avoid") return "bad";
  return "plain";
}

// The 80% range as a bar, the 50% range darker inside it, today's price as a tick.
function RangeBar({ h, price }: { h: HorizonForecast; price: number }) {
  const lo = Math.min(h.band80[0], price);
  const hi = Math.max(h.band80[1], price);
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100;
  return (
    <svg viewBox="0 0 100 14" className="range-bar" role="img"
      aria-label={`80% range ${rupees(h.band80[0])} to ${rupees(h.band80[1])}, half the time between ${rupees(h.band50[0])} and ${rupees(h.band50[1])}`}>
      <rect x={x(h.band80[0])} y="4" width={x(h.band80[1]) - x(h.band80[0])} height="6" rx="3" fill="var(--accent-soft)" />
      <rect x={x(h.band50[0])} y="4" width={x(h.band50[1]) - x(h.band50[0])} height="6" fill="var(--accent)" opacity="0.45" />
      <line x1={x(h.median)} x2={x(h.median)} y1="2" y2="12" stroke="var(--accent)" strokeWidth="1" />
      <line x1={x(price)} x2={x(price)} y1="0" y2="14" stroke="var(--ink)" strokeWidth="0.6" strokeDasharray="1.5 1" />
    </svg>
  );
}

export function ForecastPanel({ symbol }: { symbol: string }) {
  const [f, setF] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.forecast(symbol).then(
      (r) => live && setF(r),
      (e) => live && setError(e instanceof ApiError ? e.message : "Could not load the forecast"),
    );
    return () => {
      live = false;
    };
  }, [symbol]);

  return (
    <div className="panel">
      <h2>Next 1 to 2 months</h2>
      {error && <p className="error">{error}</p>}
      {!f && !error && <p className="small muted">Working out the range…</p>}
      {f && f.status !== "ok" && <p className="small muted">{f.error}.</p>}
      {f && f.status === "ok" && (
        <>
          {f.horizons.map((h) => (
            <div key={h.horizon} className="forecast-row">
              <div className="forecast-head">
                <span>
                  {LABEL[h.horizon] ?? h.horizon}: <strong>{rupees(h.median)}</strong>{" "}
                  <span className="muted small">({pct(h.median / f.price - 1, true)})</span>
                </span>
                <span className={`tag ${leanTone(h.lean)}`}>{h.lean}</span>
              </div>
              <RangeBar h={h} price={f.price} />
              <p className="small muted">
                80% likely between {rupees(h.band80[0])} and {rupees(h.band80[1])}. Chance it rises {pct(h.p_up, false, 0)},
                chance it beats the Nifty {pct(h.p_beat_nifty, false, 0)}.
                {h.results_in_window && " Results are due in this window, so the range is wider."}
              </p>
            </div>
          ))}
          <ModelNote f={f} />
        </>
      )}
    </div>
  );
}

function ModelNote({ f }: { f: Extract<Forecast, { status: "ok" }> }) {
  const t = f.model.test["1m"];
  const edge = Object.values(f.model.has_edge).some(Boolean);
  return (
    <details style={{ marginTop: "0.75rem" }}>
      <summary>How much to trust this</summary>
      <p className="small" style={{ marginTop: "0.5rem" }}>
        Built from momentum against the Nifty, last month&apos;s move, the latest results surprise and the valuation gap, with the
        range set by this stock&apos;s own volatility. Fitted on {f.model.fitted_on}, then tested on {f.model.tested_on}, which it never saw.
      </p>
      {t && t.n > 0 && (
        <p className="small" style={{ marginTop: "0.5rem" }}>
          In that test, 1 month ahead: ranking correlation {t.rank_ic?.toFixed(2) ?? "–"}
          {t.rank_ic_t != null && ` (t ${t.rank_ic_t.toFixed(1)})`}, the 80% range held {pct(t.coverage_80, false, 0)} of outcomes, and the
          direction against the Nifty was right {pct(t.direction_right, false, 0)} of the time.
        </p>
      )}
      <p className="small muted" style={{ marginTop: "0.5rem" }}>
        {edge
          ? "The test showed some skill, so strong readings get a lean. It is a tilt in the odds, not a prediction."
          : "The test did not show skill at picking direction, so there is no lean: read this as the likely range, not a call."}{" "}
        News and X sentiment are not in these numbers; they cannot be tested on history.
      </p>
    </details>
  );
}
