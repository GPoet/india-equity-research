"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Volume } from "@/components/MarketOverview";
import { api, ApiError, type ScanRow, type ScanStatus } from "@/lib/api";
import { pct, rupees } from "@/lib/format";

const POLL_MS = 10000;

function longDate(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function signalTone(signal: string): string {
  if (signal === "Undervalued") return "good";
  if (signal === "Overvalued") return "bad";
  if (signal === "Fairly valued") return "mid";
  return "plain";
}

function ScanTable({ rows, showFlags }: { rows: ScanRow[]; showFlags: boolean }) {
  return (
    <div className="table-scroll">
      <table className="scan-table">
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Stock</th>
            <th className="num">Price</th>
            <th className="num">Volume</th>
            <th className="num">Expected in a month</th>
            <th className="num">80% range</th>
            <th className="num">Beats Nifty</th>
            <th className="num">Rises</th>
            <th>Valuation</th>
            {showFlags && <th>Red flags</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const f = r.forecast?.["1m"];
            return (
              <tr key={r.key ?? r.symbol}>
                <td className="num muted">{i + 1}</td>
                <td>
                  {r.exchange === "BSE" ? (
                    <>
                      {r.link ? (
                        <a href={r.link} target="_blank" rel="noreferrer noopener" className="strong-link">{r.ticker ?? r.symbol}</a>
                      ) : (
                        <strong>{r.ticker ?? r.symbol}</strong>
                      )}{" "}
                      <span className="tag plain" title="Listed only on BSE">BSE</span>
                    </>
                  ) : (
                    <Link href={`/company/${encodeURIComponent(r.symbol)}`} className="strong-link">{r.symbol}</Link>
                  )}
                  <div className="stock-name">{r.name}</div>
                </td>
                <td className="num">{rupees(r.price)}</td>
                <td className="num"><Volume volume={r.volume} turnover={r.turnover} /></td>
                <td className="num">
                  {f ? (
                    <>
                      <strong>{rupees(f.median)}</strong> <span className={f.expected_return >= 0 ? "up" : "down"}>({pct(f.expected_return, true)})</span>
                      <div className="stock-name">by {longDate(f.target_date)}{f.results_in_window ? ", results due" : ""}</div>
                    </>
                  ) : "–"}
                </td>
                <td className="num">{f ? `${rupees(f.band80[0])} to ${rupees(f.band80[1])}` : "–"}</td>
                <td className="num">{f ? pct(f.p_beat_nifty, false, 0) : "–"}</td>
                <td className="num">{f ? pct(f.p_up, false, 0) : "–"}</td>
                <td>
                  <span className={`tag ${signalTone(r.signal)}`} title={r.valuation_note ?? undefined}>{r.signal}</span>
                  {r.valuation_note && showFlags && <div className="stock-name">{r.valuation_note}</div>}
                  {r.upside !== null && <div className="stock-name">fair value {pct(r.upside, true, 0)}</div>}
                </td>
                {showFlags && (
                  <td className="small">
                    {r.red_flags.join("; ") || <span className="muted">none</span>}
                    {r.model_notes && r.model_notes.length > 0 && <div className="muted">Model note: {r.model_notes.join("; ")}</div>}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// The daily scan of the Nifty 500. Runs itself after each NSE trading day; Refresh runs it now.
export function DailyScan() {
  const [status, setStatus] = useState<ScanStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    api.scan().then(
      (s) => {
        if (!live) return;
        setStatus(s);
        if (s.running) timer = setTimeout(() => setTick((t) => t + 1), POLL_MS);
      },
      (e) => live && setError(e instanceof ApiError ? e.message : "Could not load the scan"),
    );
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [tick]);

  async function refresh() {
    setBusy(true);
    setError(null);
    try {
      setStatus(await api.startScan());
      setTick((t) => t + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the scan");
    } finally {
      setBusy(false);
    }
  }

  const result = status?.latest ?? status?.partial ?? null;
  const p = status?.progress;
  return (
    <section className="card scan">
      <div className="card-head">
        <h2>Agents&apos; picks for the coming month</h2>
        <button className="primary" onClick={refresh} disabled={busy || status?.running}>
          {status?.running ? "Scanning…" : busy ? "Starting…" : "Refresh"}
        </button>
      </div>
      <p className="card-note">
        Every listed company that traded (NSE main board and SME, plus companies listed only on BSE) run through the valuation,
        quality checks, ownership and the Agents
        Forecast, ranked by the odds of beating the Nifty over the next month. Picks leave out stocks with red flags and stocks that
        traded under ₹1 crore on the day. BSE-only companies do not get the promoter pledge check yet, and their filings refresh
        weekly. Runs by itself each trading day after NSE publishes its end-of-day file (around 7 pm).
      </p>
      {error && <p className="error">{error}</p>}
      {status?.running && p?.total ? (
        <p className="small muted">
          Scanning {p.done} of {p.total}{p.current ? ` (now ${p.current})` : ""}. The first full scan downloads every company&apos;s filings
          and takes a day or two; later days take under an hour.
        </p>
      ) : null}
      {p?.error && <p className="error small">{p.error}</p>}
      {!result && !status?.running && status && <p className="muted small">No scan yet. Press Refresh to run the first one.</p>}
      {result && (
        <>
          <p className="small muted" style={{ margin: "0.5rem 0" }}>
            Prices of {longDate(result.price_day)}. {result.scanned} of {result.total} companies scanned
            {result.complete ? "" : " so far"}
            {Object.keys(result.errors).length > 0 && `, ${Object.keys(result.errors).length} could not be valued`}.
          </p>
          <ScanTable rows={showAll ? result.ranked : result.picks} showFlags={showAll} />
          <p className="small" style={{ marginTop: "0.75rem" }}>
            <button className="link" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show the picks only" : `Show all ${result.ranked.length} ranked stocks, red flags included`}
            </button>
          </p>
          <p className="small muted" style={{ marginTop: "0.5rem" }}>
            How far to trust this: tested on 2024 onwards, data it never saw, the forecast showed no measured edge at picking which stocks
            beat the Nifty, and it was fitted on Nifty 50 stocks, so it is less tested on small companies. Expected moves are small next to
            the ranges. Treat the list as a screen to research from, not a buy list. Each
            day&apos;s list is saved so its real record can be scored as the weeks pass.
          </p>
        </>
      )}
    </section>
  );
}
