import { rupees } from "@/lib/format";

type Props = {
  price: number;
  low: number;
  mid: number;
  high: number;
  buyBelow: number;
  values: { name: string; value: number }[];
};

// The fair-value scale: every formula's value as a dot, the blended range as a band, and
// today's price as a needle. Width-independent SVG (viewBox), labels in rupees.
export function ValueScale({ price, low, mid, high, buyBelow, values }: Props) {
  const all = [price, low, high, buyBelow, ...values.map((v) => v.value)].filter((v) => Number.isFinite(v));
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.06; // works for equal, zero and negative values
  const min = lo - pad;
  const max = hi + pad;
  const W = 1000;
  const x = (v: number) => 20 + ((v - min) / (max - min)) * (W - 40);
  // Keep the price label inside the drawing when the price sits near either edge.
  const px = x(price);
  const priceAnchor = px < 140 ? "start" : px > W - 140 ? "end" : "middle";
  const bandY = 58;

  return (
    <svg className="scale" viewBox={`0 0 ${W} 112`} role="img"
      aria-label={`Fair value ${rupees(low)} to ${rupees(high)}, mid ${rupees(mid)}; price ${rupees(price)}`}>
      <line x1={20} x2={W - 20} y1={bandY} y2={bandY} stroke="var(--rule-strong)" strokeWidth={2} />
      <rect x={x(low)} y={bandY - 16} width={Math.max(x(high) - x(low), 2)} height={32} rx={4}
        fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth={1} />
      <line x1={x(mid)} x2={x(mid)} y1={bandY - 16} y2={bandY + 16} stroke="var(--accent)" strokeWidth={2} />
      {values.map((v) => (
        <circle key={v.name} cx={x(v.value)} cy={bandY} r={4} fill="var(--surface)" stroke="var(--ink)" strokeWidth={1.2}>
          <title>{`${v.name}: ${rupees(v.value)}`}</title>
        </circle>
      ))}
      <line x1={x(buyBelow)} x2={x(buyBelow)} y1={bandY - 22} y2={bandY + 40} stroke="var(--tailwind)" strokeWidth={2} strokeDasharray="4 3" />
      <line x1={x(price)} x2={x(price)} y1={14} y2={bandY + 30} stroke="var(--ink)" strokeWidth={3} />
      <text x={px} y={10} textAnchor={priceAnchor} className="tick-label">Price {rupees(price)}</text>
      <text x={x(low)} y={bandY + 36} textAnchor="middle">{rupees(low)}</text>
      <text x={x(high)} y={bandY + 36} textAnchor="middle">{rupees(high)}</text>
    </svg>
  );
}

export function ScaleKey({ mid, low, high, buyBelow }: { mid: number; low: number; high: number; buyBelow: number }) {
  return (
    <>
      <p style={{ marginTop: "0.25rem" }}>
        <strong>Fair value {rupees(mid)}</strong> (range {rupees(low)} to {rupees(high)}).{" "}
        <span style={{ color: "var(--tailwind)", fontWeight: 600 }}>Buy below {rupees(buyBelow)}</span> for a 15% margin
        of safety.
      </p>
      <p className="small muted" style={{ marginTop: "0.25rem" }}>
      Each dot is one formula&apos;s value (hover for its name). The shaded band is the middle of the weighted values, the
      line inside it the weighted fair value, and the dashed line the buy-below price.
      </p>
    </>
  );
}
