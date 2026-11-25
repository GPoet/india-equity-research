"use client";

import { useEffect, useState } from "react";

import { stanceTone } from "@/components/SectorPanel";
import { api, ApiError, type SectorStat } from "@/lib/api";
import { pct } from "@/lib/format";

function Bar({ value }: { value: number | null }) {
  if (value === null) return <span className="muted">–</span>;
  const w = Math.min(Math.abs(value) / 0.3, 1) * 3;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", justifyContent: "flex-end", width: "100%" }}>
      <span className="weight-bar" style={{ width: `${w}rem`, background: value >= 0 ? "var(--tailwind)" : "var(--headwind)" }} />
      {pct(value, true)}
    </span>
  );
}

export default function SectorsPage() {
  const [data, setData] = useState<{ as_of: string; sectors: SectorStat[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.sectors().then(setData, (e) => setError(e instanceof ApiError ? e.message : "Could not load sectors"));
  }, []);

  return (
    <article>
      <h1 style={{ fontSize: "var(--step-2)", fontWeight: 800 }}>Sectors, strongest first</h1>
      <p className="muted" style={{ margin: "0.5rem 0 1.5rem", maxWidth: "46rem" }}>
        Each sector&apos;s NSE index against the Nifty 50. Bullish means ahead of the market over 3 and 6 months and above its
        200-day average. Sectors NSE launched in 2026 are judged on 3 months and marked short history.
        {data && <> Data to {data.as_of}.</>}
      </p>
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">Loading NSE index data…</p>}
      {data && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th className="num">Rank</th>
                <th>Sector</th>
                <th>Stance</th>
                <th className="num">vs Nifty, 3 months</th>
                <th className="num">vs Nifty, 6 months</th>
                <th className="num">vs 200-day average</th>
                <th className="num">P/E</th>
              </tr>
            </thead>
            <tbody>
              {data.sectors.map((s) => (
                <tr key={s.key}>
                  <td className="num">{s.rank || "–"}</td>
                  <td>{s.label}</td>
                  <td><span className={`tag ${stanceTone(s.stance)}`}>{s.stance}</span></td>
                  <td className="num"><Bar value={s.rs_3m} /></td>
                  <td className="num"><Bar value={s.rs_6m} /></td>
                  <td className="num">{pct(s.vs_200dma, true)}</td>
                  <td className="num">{s.pe !== null ? s.pe.toFixed(1) : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}
