"use client";

import Link from "next/link";
import { createContext, useContext, useEffect, useState } from "react";

import { PeriodSwitch } from "@/components/PeriodSwitch";
import { api, ApiError, type Mover, type Overview, type Period } from "@/lib/api";
import { passes, type Filters } from "@/lib/filters";
import { crore, pct, rupees, shares } from "@/lib/format";

const SHOWN = 10;

function longDate(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function Change({ x }: { x: number | null }) {
  if (x === null) return <span className="muted">–</span>;
  if (Math.abs(x) < 0.0005) return <span className="muted">0.0%</span>;
  return <span className={x > 0 ? "up" : "down"}>{pct(x, true)}</span>;
}

// BSE-only companies ("BSE:<code>"): their ticker and BSE page, from the overview payload.
const MetaContext = createContext<NonNullable<Overview["meta"]>>({});

export const THIN_TURNOVER = 1e7; // under Rs 1 crore a day: hard to buy or sell in size

function Stock({ symbol, names }: { symbol: string; names: Record<string, string> }) {
  const meta = useContext(MetaContext)[symbol];
  if (symbol.startsWith("BSE:")) {
    const label = meta?.ticker ?? symbol.slice(4);
    return (
      <span className="stock">
        <span>
          {meta?.link ? (
            <a href={meta.link} target="_blank" rel="noreferrer noopener">{label}</a>
          ) : (
            <strong>{label}</strong>
          )}{" "}
          <span className="tag plain" title="Listed only on BSE">BSE</span>
        </span>
        <span className="stock-name">{names[symbol] ?? ""}</span>
      </span>
    );
  }
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
      <span className="vol-value">
        {crore(turnover)}
        {turnover < THIN_TURNOVER && (
          <span className="thin" title="Under ₹1 crore traded: hard to buy or sell in size"> thin</span>
        )}
      </span>
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

function MoversCard({
  title,
  data,
  kind,
  names,
  filters,
}: {
  title: string;
  data: Overview["movers"];
  kind: "best" | "worst";
  names: Record<string, string>;
  filters: Filters;
}) {
  const [period, setPeriod] = useState<Period>("day");
  return (
    <Card title={title} action={<PeriodSwitch value={period} onChange={setPeriod} label={`${title} period`} />}>
      <MoverList rows={data[period][kind].filter((r) => passes(r, filters)).slice(0, SHOWN)} names={names} />
    </Card>
  );
}

export function MarketOverview({ filters }: { filters: Filters }) {
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
    <MetaContext.Provider value={data.meta ?? {}}>
      <p className="market-asof">
        Last trading day {longDate(data.as_of)}. {data.universe}, trading at least ₹10 lakh a day, from the exchanges&apos; end-of-day files.
        &ldquo;Thin&rdquo; marks stocks under ₹1 crore a day. Search
        any company above.
      </p>
      <div className="grid">
        <Card title="Top sectors" action={<PeriodSwitch value={sectorPeriod} onChange={setSectorPeriod} label="Sector period" />}>
          <SectorBars rows={data.sectors[sectorPeriod]} />
        </Card>
        <MoversCard title="Top stocks" data={data.movers} kind="best" names={n} filters={filters} />
        <MoversCard title="Worst performers" data={data.movers} kind="worst" names={n} filters={filters} />

        <Card title="Stocks of the day" note="Most traded by value on the last trading day.">
          <Heads cols={["Stock", "Price", "Volume", "Change"]} />
          <ol className="rows four">
            {data.most_traded.filter((r) => passes(r, filters)).slice(0, SHOWN).map((t) => (
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
            {data.trending.filter((r) => passes(r, filters)).slice(0, SHOWN).map((t) => (
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
            {data.news.filter((r) => passes(r, filters)).map((x) => (
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
    </MetaContext.Provider>
  );
}
