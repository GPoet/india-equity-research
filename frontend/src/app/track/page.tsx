"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, ApiError, type Backtest, type Journal, type SignalSummary } from "@/lib/api";
import { pct, rupees } from "@/lib/format";

const HORIZONS = ["1m", "3m", "6m", "12m"];
const HORIZON_LABEL: Record<string, string> = { "1m": "1 month", "3m": "3 months", "6m": "6 months", "12m": "1 year" };

function signalTone(signal: string): string {
  return signal === "Undervalued" ? "good" : signal === "Overvalued" ? "bad" : "mid";
}

// The hit rate a coin would get: share of all calls where the stock beat (or lagged) the Nifty.
function chance(signal: string, base: number | null | undefined): number | null {
  if (base === null || base === undefined) return null;
  if (signal === "Undervalued") return base;
  if (signal === "Overvalued") return 1 - base;
  return null;
}

function SummaryTable({
  rows,
  horizons,
  baseRate,
}: {
  rows: SignalSummary[];
  horizons: string[];
  baseRate?: Record<string, number | null>;
}) {
  const shown = rows.filter((r) => horizons.includes(r.horizon) && (r.n > 0 || r.pending > 0));
  if (shown.length === 0) return <p className="muted">No calls scored yet.</p>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Signal</th>
            <th>After</th>
            <th className="num">Calls scored</th>
            <th className="num">Right</th>
            {baseRate && <th className="num">By chance</th>}
            <th className="num">Average vs Nifty</th>
            <th className="num">Median vs Nifty</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
              <tr key={r.signal + r.horizon}>
                <td><span className={`tag ${signalTone(r.signal)}`}>{r.signal}</span></td>
                <td>{HORIZON_LABEL[r.horizon]}</td>
                <td className="num">{r.n}{r.pending > 0 && <span className="muted"> (+{r.pending} pending)</span>}</td>
                <td className="num">{pct(r.hit_rate, false, 0)}</td>
                {baseRate && <td className="num muted">{pct(chance(r.signal, baseRate[r.horizon]), false, 0)}</td>}
                <td className="num">{pct(r.mean_excess, true)}</td>
                <td className="num">{pct(r.median_excess, true)}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

export default function TrackPage() {
  const [journal, setJournal] = useState<Journal | null>(null);
  const [backtest, setBacktest] = useState<Backtest | null>(null);
  const [backtestMissing, setBacktestMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.journal().then(setJournal, (e) => setError(e instanceof ApiError ? e.message : "Could not load the journal"));
    api.backtest().then(setBacktest, (e) => {
      if (e instanceof ApiError && e.status === 404) setBacktestMissing(true);
      else setError(e instanceof ApiError ? e.message : "Could not load the backtest");
    });
  }, []);

  return (
    <article>
      <h1 style={{ fontSize: "var(--step-2)", fontWeight: 800 }}>Does the signal work?</h1>
      <p className="muted" style={{ margin: "0.5rem 0 2rem", maxWidth: "46rem" }}>
        A call counts as right when an undervalued stock then beats the Nifty 50, an overvalued one lags it, or a fairly valued one
        stays within 10% of it. Returns are share-price changes, dividends excluded.
      </p>
      {error && <p className="error">{error}</p>}

      <section>
        <h2>History test</h2>
        {backtestMissing && (
          <p className="muted">No backtest yet. Run <code>uv run python scripts/backtest.py</code> in the backend folder.</p>
        )}
        {!backtest && !backtestMissing && !error && <p className="muted">Loading…</p>}
        {backtest && (
          <>
            <p className="note">
              The valuation engine re-run every quarter from {backtest.start} to {backtest.end} on the {backtest.universe}, using only
              filings and prices public on each date, with prices put back on each date&apos;s share basis.{" "}
              {backtest.summary.observations} valuations from {backtest.symbols} companies, engine version {backtest.engine_version}.
              {backtest.summary.usable !== undefined && (
                <>
                  {" "}Scored: {backtest.summary.usable}. Left out:{" "}
                  {Object.entries(backtest.summary.excluded ?? {}).map(([why, n]) => `${n} ${why}`).join(", ") || "none"}.
                </>
              )}
            </p>
            <SummaryTable rows={backtest.summary.by_signal} horizons={["6m", "12m"]} baseRate={backtest.summary.base_rate} />
            {backtest.summary.base_rate && (
              <p className="small muted" style={{ marginTop: "0.5rem" }}>
                By chance: how often you would be right calling every stock the same way. A signal only adds something if Right beats it.
              </p>
            )}
            <h3 style={{ margin: "1.5rem 0 0.5rem" }}>Bigger estimated upside, bigger return?</h3>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>After</th>
                    <th className="num">Rank correlation</th>
                    <th className="num">Top fifth by upside, vs Nifty</th>
                    <th className="num">Bottom fifth, vs Nifty</th>
                  </tr>
                </thead>
                <tbody>
                  {HORIZONS.map((h) => {
                    const s = backtest.summary.upside_vs_return[h];
                    return (
                      <tr key={h}>
                        <td>{HORIZON_LABEL[h]}</td>
                        <td className="num">{s?.spearman === null || s?.spearman === undefined ? "–" : s.spearman.toFixed(2)}</td>
                        <td className="num">{pct(s?.top_quintile_excess, true)}</td>
                        <td className="num">{pct(s?.bottom_quintile_excess, true)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="small muted" style={{ marginTop: "0.5rem" }}>
              Rank correlation runs from −1 to 1; 0 means the estimated upside told you nothing about what came next.
            </p>
            <h3 style={{ margin: "1.5rem 0 0.5rem" }}>Limits of this test</h3>
            <ul className="small">{backtest.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          </>
        )}
      </section>

      <section>
        <h2>Calls made here</h2>
        <p className="note">Every company page you open is recorded once a day and scored as time passes.</p>
        {journal && journal.entries.length === 0 && <p className="muted">No calls yet. Open a company to make the first.</p>}
        {journal && journal.entries.length > 0 && (
          <>
            <SummaryTable rows={journal.summary} horizons={HORIZONS} />
            <div className="table-scroll" style={{ marginTop: "1.5rem" }}>
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Company</th>
                    <th className="num">Price then</th>
                    <th>Signal</th>
                    {HORIZONS.map((h) => <th key={h} className="num">{HORIZON_LABEL[h]}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {journal.entries.map((e) => (
                    <tr key={e.id}>
                      <td>{e.day}</td>
                      <td><Link href={`/company/${encodeURIComponent(e.symbol)}`}>{e.symbol}</Link></td>
                      <td className="num">{rupees(e.price)}</td>
                      <td><span className={`tag ${signalTone(e.signal)}`}>{e.signal}</span></td>
                      {HORIZONS.map((h) => {
                        const s = e.scores[h];
                        if (!s || s.outcome === "pending") return <td key={h} className="num muted">pending</td>;
                        if (s.excess === null) return <td key={h} className="num muted">no data</td>;
                        return (
                          <td key={h} className="num" style={{ color: s.outcome === "hit" ? "var(--tailwind)" : "var(--headwind)" }}>
                            {pct(s.excess, true)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </article>
  );
}
