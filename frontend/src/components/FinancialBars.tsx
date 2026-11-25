import type { YearRow } from "@/lib/api";
import { crore, fyLabel } from "@/lib/format";

// Revenue (or total income for banks) and profit by fiscal year, as paired bars.
export function FinancialBars({ years, isBank }: { years: YearRow[]; isBank: boolean }) {
  const rows = years.filter((y) => y.revenue !== null);
  if (rows.length === 0) return <p className="muted">No annual figures available.</p>;
  const W = 760;
  const H = 220;
  const top = Math.max(0, ...rows.map((y) => Math.max(y.revenue ?? 0, y.profit ?? 0)));
  const minProfit = Math.min(0, ...rows.map((y) => y.profit ?? 0));
  const span = top - minProfit || 1;
  const zero = 20 + (top / span) * (H - 50);
  const yOf = (v: number) => 20 + ((top - v) / span) * (H - 50);
  const slot = (W - 20) / rows.length;
  const bw = Math.min(28, slot / 3);
  return (
    <figure style={{ margin: 0 }}>
      <div className="legend">
        <span><span className="swatch" style={{ background: "var(--rule-strong)" }} />{isBank ? "Total income" : "Revenue"}</span>
        <span><span className="swatch" style={{ background: "var(--accent)" }} />Profit to shareholders</span>
      </div>
      <svg className="bars" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Revenue and profit by fiscal year">
        <line x1={10} x2={W - 10} y1={zero} y2={zero} stroke="var(--rule-strong)" />
        {rows.map((y, i) => {
          const cx = 20 + slot * i + slot / 2;
          const r = y.revenue ?? 0;
          const p = y.profit; // missing profit draws no bar, never a zero bar
          return (
            <g key={y.fy_end}>
              <rect x={cx - bw - 1} y={yOf(r)} width={bw} height={Math.max(zero - yOf(r), 0)} fill="var(--rule-strong)">
                <title>{`${fyLabel(y.fy_end)} ${isBank ? "total income" : "revenue"} ${crore(r)}`}</title>
              </rect>
              {p !== null && (
                <rect x={cx + 1} y={p >= 0 ? yOf(p) : zero} width={bw} height={Math.abs(yOf(p) - zero)}
                  fill={p >= 0 ? "var(--accent)" : "var(--headwind)"} strokeDasharray={p < 0 ? "3 2" : undefined}
                  stroke={p < 0 ? "var(--ink)" : undefined}>
                  <title>{`${fyLabel(y.fy_end)} ${p < 0 ? "loss" : "profit"} ${crore(p)}`}</title>
                </rect>
              )}
              <text x={cx} y={H - 8} textAnchor="middle">{fyLabel(y.fy_end)}</text>
            </g>
          );
        })}
      </svg>
      <figcaption className="small muted">
        Latest year: {isBank ? "total income" : "revenue"} {crore(rows.at(-1)?.revenue)}, profit {crore(rows.at(-1)?.profit)}.
        From the company&apos;s NSE results filings{rows.some((y) => y.source === "sum_of_quarters") ? "; some years add up four quarters" : ""}.
      </figcaption>
    </figure>
  );
}

