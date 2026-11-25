"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type SectorPicture, type SectorStat } from "@/lib/api";
import { pct } from "@/lib/format";

export function stanceTone(stance: string): string {
  if (stance.startsWith("bullish")) return "good";
  if (stance.startsWith("bearish")) return "bad";
  if (stance.startsWith("neutral")) return "mid";
  return "plain";
}

function Stance({ s }: { s: SectorStat }) {
  return <span className={`tag ${stanceTone(s.stance)}`}>{s.stance}</span>;
}

export function SectorPanel({ symbol }: { symbol: string }) {
  const [data, setData] = useState<SectorPicture | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.sector(symbol).then(
      (d) => live && setData(d),
      (e) => live && setError(e instanceof ApiError ? e.message : "Could not load the sector view"),
    );
    return () => {
      live = false;
    };
  }, [symbol]);

  return (
    <div className="panel">
      <h2>Sector</h2>
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">Loading sector data…</p>}
      {data && !data.picture.sector && (
        <p className="muted">
          No sector index matches NSE&apos;s industry label &ldquo;{data.industry ?? "unknown"}&rdquo;.
        </p>
      )}
      {data?.picture.sector && (
        <>
          <p>
            <strong>{data.picture.sector.label}</strong> <Stance s={data.picture.sector} />
          </p>
          <p className="small muted" style={{ marginTop: "0.25rem" }}>
            Rank {data.picture.sector.rank} of {data.picture.sector.of}. Against the Nifty 50:{" "}
            {pct(data.picture.sector.rs_3m, true)} over 3 months, {pct(data.picture.sector.rs_6m, true)} over 6.
            {data.picture.sector.pe !== null && <> Sector P/E {data.picture.sector.pe.toFixed(1)}.</>}
          </p>
          <h3 style={{ marginTop: "1rem" }}>Related sectors</h3>
          <ul className="related">
            {data.picture.related.map((r) => (
              <li key={r.stat.key}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
                  <span>{r.stat.label}</span>
                  <Stance s={r.stat} />
                </div>
                <div className="why">
                  {r.basis === "economic link" ? r.why : "Moves with it beyond the market"}
                  {r.correlation !== null && <>, correlation {r.correlation.toFixed(2)}</>}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
