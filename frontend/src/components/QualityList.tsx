import type { Lens } from "@/lib/api";

const GOOD = new Set(["strong", "safe", "unlikely manipulator", "passes", "passes so far", "creates value", "beats bonds", "clean", "no promoter"]);
const BAD = new Set(["weak", "distress", "possible manipulation", "fails", "destroys value", "below bonds", "heavy pledge", "promoter selling"]);

function tone(verdict: string | null): string {
  if (!verdict) return "plain";
  if (GOOD.has(verdict)) return "good";
  if (BAD.has(verdict)) return "bad";
  return "mid";
}

// Quality, safety and screening checks: verdict first, the formula's own words second.
export function QualityList({ lenses }: { lenses: Lens[] }) {
  const rows = lenses.filter((l) => l.kind !== "value");
  return (
    <table>
      <tbody>
        {rows.map((l) => (
          <tr key={l.key} className={l.applicable ? "" : "na"}>
            <td style={{ width: "34%" }}>
              <strong>{l.name}</strong>
              <div className="small muted">{l.school}</div>
            </td>
            <td style={{ width: "9rem" }}>
              {l.applicable ? <span className={`tag ${tone(l.verdict)}`}>{l.verdict ?? "measured"}</span> : <span className="tag plain">does not apply</span>}
            </td>
            <td className="small">{l.applicable ? l.summary : l.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
