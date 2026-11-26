"use client";

import { DEFAULT_FILTERS, isDefault, setFilters, type Board, type Filters, type ValuationBucket } from "@/lib/filters";

const BOARDS: [Board, string, string][] = [
  ["main", "Main board", "NSE main board"],
  ["sme", "SME", "NSE Emerge and BSE SME platforms"],
  ["bse", "BSE-only", "Main-board companies listed only on BSE"],
];
const VALUATIONS: [ValuationBucket, string][] = [
  ["under", "Undervalued"],
  ["fair", "Fairly valued"],
  ["over", "Overvalued"],
  ["none", "Not valued"],
];

function Chip({ on, label, title, onClick }: { on: boolean; label: string; title?: string; onClick: () => void }) {
  return (
    <button type="button" className="chip" aria-pressed={on} title={title} onClick={onClick}>
      {label}
    </button>
  );
}

export function FilterBar({ filters }: { filters: Filters }) {
  const f = filters;
  return (
    <div className="filter-bar" role="group" aria-label="Filter stocks">
      <div className="filter-group">
        <span className="filter-label">Board</span>
        {BOARDS.map(([key, label, title]) => (
          <Chip key={key} on={f.boards[key]} label={label} title={title}
            onClick={() => setFilters({ ...f, boards: { ...f.boards, [key]: !f.boards[key] } })} />
        ))}
      </div>
      <div className="filter-group">
        <span className="filter-label">Valuation</span>
        {VALUATIONS.map(([key, label]) => (
          <Chip key={key} on={f.valuation[key]} label={label}
            onClick={() => setFilters({ ...f, valuation: { ...f.valuation, [key]: !f.valuation[key] } })} />
        ))}
      </div>
      <div className="filter-group">
        <label className="filter-label" htmlFor="penny">Penny stocks</label>
        <select id="penny" className="filter-select" value={f.penny}
          onChange={(e) => setFilters({ ...f, penny: Number(e.target.value) as Filters["penny"] })}>
          <option value={0}>Show</option>
          <option value={10}>Hide under ₹10</option>
          <option value={20}>Hide under ₹20</option>
          <option value={50}>Hide under ₹50</option>
        </select>
        <Chip on={f.hideThin} label="Hide thin trading" title="Under ₹1 crore traded a day"
          onClick={() => setFilters({ ...f, hideThin: !f.hideThin })} />
        <Chip on={f.hideRed} label="Hide red flags" title="Distress, possible manipulation, weak scores, heavy pledges, promoter selling"
          onClick={() => setFilters({ ...f, hideRed: !f.hideRed })} />
        {!isDefault(f) && (
          <button type="button" className="link small" onClick={() => setFilters(DEFAULT_FILTERS)}>Reset</button>
        )}
      </div>
    </div>
  );
}
