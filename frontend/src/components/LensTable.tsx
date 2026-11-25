import type { Blend, Lens } from "@/lib/api";
import { pct, rupees } from "@/lib/format";

// Value formulas: what each says the share is worth, who uses it, and its weight in the blend.
export function LensTable({ lenses, blend, price }: { lenses: Lens[]; blend: Blend; price: number }) {
  const rows = lenses.filter((l) => l.kind === "value");
  const maxWeight = Math.max(0.0001, ...Object.values(blend.used));
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Formula</th>
            <th className="col-school">Used by</th>
            <th className="num">Value per share</th>
            <th className="num">vs price</th>
            <th>Weight</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((l) => {
            const w = blend.used[l.key];
            return (
              <tr key={l.key} className={l.applicable ? "" : "na"}>
                <td>
                  <details>
                    <summary style={{ color: "inherit", fontWeight: 600 }}>{l.name}</summary>
                    <p className="small muted" style={{ marginTop: "0.25rem" }}>
                      {l.school}. {l.applicable ? l.summary : l.reason}
                    </p>
                  </details>
                </td>
                <td className="col-school">{l.school}</td>
                <td className="num">{l.applicable ? rupees(l.value) : "does not apply"}</td>
                <td className="num">
                  {l.applicable && l.value !== null ? pct(l.value / price - 1, true, 0) : ""}
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  {w ? (
                    <span title={pct(w, false, 0)}>
                      <span className="weight-bar" style={{ width: `${(w / maxWeight) * 4}rem` }} />{" "}
                      <span className="small muted">{pct(w, false, 0)}</span>
                    </span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
