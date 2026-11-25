import type { Lens } from "@/lib/api";
import { pct } from "@/lib/format";

const ROWS: [string, string][] = [
  ["promoter_pct", "Promoters"],
  ["fpi_pct", "Foreign institutions"],
  ["dii_pct", "Domestic institutions"],
  ["mf_pct", "of which mutual funds"],
  ["retail_pct", "Individuals"],
];

// Who owns the company, from its latest NSE shareholding pattern.
export function OwnershipPanel({ lens }: { lens: Lens | undefined }) {
  if (!lens || !lens.applicable) return null;
  const v = lens.inputs;
  const pledged = v.pledged_of_promoter as number | null;
  return (
    <div className="panel">
      <h2>Who owns it</h2>
      <table>
        <tbody>
          {ROWS.map(([key, label]) => (
            <tr key={key}>
              <td style={key === "mf_pct" ? { paddingLeft: "1.25rem" } : undefined}>{label}</td>
              <td className="num">{pct(v[key] as number | null)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {pledged !== null && pledged !== undefined && Number(v.promoter_pct) > 0 && (
        <p className="small" style={{ marginTop: "0.75rem" }}>
          {pledged > 0 ? <>{pct(pledged)} of the promoters&apos; shares are pledged.</> : "No promoter shares are pledged."}
        </p>
      )}
      <p className="small muted" style={{ marginTop: "0.5rem" }}>{lens.summary}</p>
    </div>
  );
}
