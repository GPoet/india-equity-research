"use client";

import { useEffect, useState } from "react";

import { FinancialBars } from "@/components/FinancialBars";
import { LensTable } from "@/components/LensTable";
import { OwnershipPanel } from "@/components/OwnershipPanel";
import { QualityList } from "@/components/QualityList";
import { ResearchPanel } from "@/components/ResearchPanel";
import { SectorPanel } from "@/components/SectorPanel";
import { SentimentPanel } from "@/components/SentimentPanel";
import { ScaleKey, ValueScale } from "@/components/ValueScale";
import { api, ApiError, type Company } from "@/lib/api";
import { crore, num, pct, rupees } from "@/lib/format";

function signalClass(signal: string): string {
  if (signal === "Undervalued") return "under";
  if (signal === "Overvalued") return "over";
  return "fair";
}

export function CompanyView({ symbol }: { symbol: string }) {
  const [company, setCompany] = useState<Company | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.company(symbol).then(
      (c) => live && setCompany(c),
      (e) => live && setError(e instanceof ApiError ? e.message : "Could not load this company"),
    );
    return () => {
      live = false;
    };
  }, [symbol]);

  if (error) return <p className="error">{error}</p>;
  if (!company) return <p className="muted">Reading {symbol}&apos;s filings and prices…</p>;

  const v = company.valuation;
  const b = v.result;
  const a = v.assumptions;
  const values = v.lenses
    .filter((l) => l.kind === "value" && l.applicable && l.value !== null && b.used[l.key])
    .map((l) => ({ name: l.name, value: l.value as number }));
  const isBank = v.company_type === "bank";

  return (
    <article>
      <div className="company-head">
        <h1>{company.name}</h1>
        <span className="sub">
          NSE: {company.symbol}
          {company.industry ? `, ${company.industry}` : ""}
        </span>
      </div>
      <p className="small muted">
        Market cap {crore(a.market_cap)}
        {a.eps_ttm && a.eps_ttm > 0 ? `, P/E ${num(v.price / a.eps_ttm, 1)}` : ""}. Price as of{" "}
        {v.price_as_of.slice(0, 16).replace("T", " ")} (Yahoo, about 15 minutes delayed).
      </p>

      <div className="verdict">
        <div className="verdict-line">
          <span className="price">{rupees(v.price)}</span>
          <span className={`signal ${signalClass(b.signal)}`}>{b.signal}</span>
          <span className="confidence">{b.confidence} confidence</span>
        </div>
        {b.low !== null && b.mid !== null && b.high !== null && b.buy_below !== null ? (
          <>
            <ValueScale price={v.price} low={b.low} mid={b.mid} high={b.high} buyBelow={b.buy_below} values={values} />
            <ScaleKey mid={b.mid} low={b.low} high={b.high} buyBelow={b.buy_below} />
          </>
        ) : (
          <p className="muted" style={{ marginTop: "1rem" }}>
            {b.reasons.length > 0 ? `${b.reasons.join(". ")}.` : "No fair value could be computed."}
          </p>
        )}
        {v.implied_growth.applicable && <p className="priced-in">{v.implied_growth.summary}.</p>}
        {(b.reasons.length > 0 || b.red_flags.length > 0) && b.mid !== null && (
          <p className="small muted" style={{ marginTop: "0.5rem" }}>
            {b.red_flags.length > 0 && <>Red flags: {b.red_flags.join("; ")}. </>}
            {b.reasons.length > 0 && <>Confidence lowered because: {b.reasons.join("; ").toLowerCase()}.</>}
          </p>
        )}
      </div>

      <div className="body">
        <div>
          <section>
            <h2>What each formula says it is worth</h2>
            <p className="note">
              Cost of equity {pct(a.cost_of_equity)}, WACC {pct(a.wacc)}, expected growth {pct(a.growth)}, beta {num(a.beta)}.
              Market rates as of {a.market_inputs_as_of}. Open a formula to see how it was worked out.
            </p>
            <LensTable lenses={v.lenses} blend={b} price={v.price} />
          </section>

          <section>
            <h2>Financial history</h2>
            <p className="note">{v.company_type === "bank" ? "Bank figures follow the banking format." : "Consolidated figures."}</p>
            <FinancialBars years={company.financials.years} isBank={isBank} />
          </section>

          <section>
            <h2>Quality and safety checks</h2>
            <p className="note">Scores and screens used by well-known investors. These do not change the fair value.</p>
            <QualityList lenses={v.lenses} />
          </section>

          <ResearchPanel symbol={company.symbol} />

          {(a.notes.length > 0 || v.warnings.length > 0) && (
            <section>
              <h2>Data notes</h2>
              <ul className="small muted">
                {[...a.notes, ...v.warnings].map((n, i) => <li key={`${i}-${n}`}>{n}</li>)}
              </ul>
            </section>
          )}
        </div>
        <aside>
          <SectorPanel symbol={company.symbol} />
          <OwnershipPanel lens={v.lenses.find((l) => l.key === "promoter")} />
          <SentimentPanel symbol={company.symbol} />
        </aside>
      </div>
    </article>
  );
}
