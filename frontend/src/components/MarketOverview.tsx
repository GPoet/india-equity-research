"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PeriodSwitch } from "@/components/PeriodSwitch";
import { api, ApiError, type Mover, type Overview, type Period } from "@/lib/api";
import { crore, pct, rupees, shares } from "@/lib/format";

function longDate(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function Change({ x }: { x: number | null }) {
  if (x === null) return <span className="muted">–</span>;
  if (Math.abs(x) < 0.0005) return <span className="muted">0.0%</span>;
  return <span className={x > 0 ? "up" : "down"}>{pct(x, true)}</span>;
}

function Stock({ symbol, names }: { symbol: string; names: Record<string, string> }) {
  return (
    <span className="stock">
      <Link href={`/company/${encodeURIComponent(symbol)}`}>{symbol}</Link>
      <span className="stock-name">{names[symbol] ?? ""}</span>
    </span>
  );
}

function Card({ title, note, children, action }: { title: string; note?: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2>{title}</h2>
        {action}
      </div>
      {note && <p className="card-note">{note}</p>}
      {children}
    </section>
  );
}

export function Volume({ volume, turnover }: { volume: number; turnover: number }) {
  return (
    <span className="row-num vol">
      {shares(volume)}
      <span className="vol-value">{crore(turnover)}</span>
    </span>
  );
}

function Heads({ cols }: { cols: string[] }) {
  return (
    <div className="row-heads" aria-hidden="true">
      {cols.map((c, i) => (
        <span key={c} className={i ? "row-num" : ""}>{c}</span>
      ))}
    </div>
  );
}

function MoverList({ rows, names }: { rows: Mover[]; names: Record<string, string> }) {
  if (rows.length === 0) return <p className="muted small">Nothing to show.</p>;
  return (
    <>
      <Heads cols={["Stock", "Price", "Volume", "Change"]} />
      <ol className="rows four">
        {rows.map((m) => (
          <li key={m.symbol}>
            <Stock symbol={m.symbol} names={names} />
            <span className="row-num">{rupees(m.close)}</span>
            <Volume volume={m.volume} turnover={m.turnover} />
            <span className="row-num"><Change x={m.change} /></span>
          </li>
        ))}
      </ol>
    </>
  );
}

function SectorBars({ rows }: { rows: Overview["sectors"][Period] }) {
  const shown = rows.slice(0, 10);
  const max = Math.max(...rows.map((r) => Math.abs(r.change)), 0.0001);
  return (
    <ol className="rows">
      {shown.map((r) => (
        <li key={r.index} className="sector-row">
          <span>{r.sector}</span>
          <span className="bar-track" aria-hidden="true">
            <span className={`bar ${r.change >= 0 ? "up" : "down"}`} style={{ width: `${(Math.abs(r.change) / max) * 100}%` }} />
          </span>
          <span className="row-num"><Change x={r.change} /></span>
        </li>
      ))}
    </ol>
  );
}

function MoversCard({ title, data, kind, names }: { title: string; data: Overview["movers"]; kind: "best" | "worst"; names: Record<string, string> }) {
  const [period, setPeriod] = useState<Period>("day");
  return (
    <Card title={title} action={<PeriodSwitch value={period} onChange={setPeriod} label={`${title} period`} />}>
      <MoverList rows={data[period][kind]} names={names} />
    </Card>
  );
}

export function MarketOverview() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sectorPeriod, setSectorPeriod] = useState<Period>("day");

  useEffect(() => {
    let live = true;
    api.overview().then(
      (d) => live && setData(d),
      (e) => live && setError(e instanceof ApiError ? e.message : "Could not load the market overview"),
    );
    return () => {
      live = false;
    };
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading the market… the first load of the day reads a month of NSE files and takes about a minute.</p>;
  const n = data.names;
  return (
    <>
      <p className="market-asof">
        Last trading day {longDate(data.as_of)}. {data.universe} stocks trading at least ₹10 crore a day, from NSE&apos;s end-of-day files. Search
        any company above.
      </p>
      <div className="grid">
        <Card title="Top sectors" action={<PeriodSwitch value={sectorPeriod} onChange={setSectorPeriod} label="Sector period" />}>
          <SectorBars rows={data.sectors[sectorPeriod]} />
        </Card>
        <MoversCard title="Top stocks" data={data.movers} kind="best" names={n} />
        <MoversCard title="Worst performers" data={data.movers} kind="worst" names={n} />

        <Card title="Stocks of the day" note="Most traded by value on the last trading day.">
          <Heads cols={["Stock", "Price", "Volume", "Change"]} />
          <ol className="rows four">
            {data.most_traded.map((t) => (
              <li key={t.symbol}>
                <Stock symbol={t.symbol} names={n} />
                <span className="row-num">{rupees(t.close)}</span>
                <Volume volume={t.volume} turnover={t.turnover} />
                <span className="row-num"><Change x={t.change} /></span>
              </li>
            ))}
          </ol>
        </Card>
        <Card title="Trending" note="Trading far above their usual volume: the last trading day against the 20 before it.">
          <Heads cols={["Stock", "Volume", "vs usual", "Change"]} />
          <ol className="rows four">
            {data.trending.map((t) => (
              <li key={t.symbol}>
                <Stock symbol={t.symbol} names={n} />
                <Volume volume={t.volume} turnover={t.turnover} />
                <span className="row-num vol">
                  {t.ratio.toFixed(1)}×<span className="vol-value">avg {shares(t.avg_volume)}</span>
                </span>
                <span className="row-num"><Change x={t.change} /></span>
              </li>
            ))}
          </ol>
        </Card>
        <Card title="News moving the week" note="What the week's biggest movers filed with NSE.">
          {data.news.length === 0 && <p className="muted small">No filings from this week&apos;s biggest movers.</p>}
          <ul className="news">
            {data.news.map((x) => (
              <li key={x.symbol + x.when}>
                <div className="news-head">
                  <Stock symbol={x.symbol} names={n} />
                  <Change x={x.change} />
                </div>
                <p className="small">
                  {x.url ? <a href={x.url} target="_blank" rel="noreferrer noopener">{x.text}</a> : x.text}
                </p>
                <p className="small muted">{x.category}, {longDate(x.when)}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
