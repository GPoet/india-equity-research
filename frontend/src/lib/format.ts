// Number formatting pinned to Indian conventions (lakh/crore grouping), independent of the
// browser's locale.
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const CRORE = 1e7;

export function rupees(x: number | null | undefined, decimals = false): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "–";
  return "₹" + (decimals ? inr2 : inr).format(x);
}

export function crore(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "–";
  return "₹" + inr.format(x / CRORE) + " cr";
}

export function pct(x: number | null | undefined, signed = false, digits = 1): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "–";
  const s = (x * 100).toFixed(digits) + "%";
  return signed && x > 0 ? "+" + s : s;
}

export function num(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "–";
  return x.toFixed(digits);
}

export function fyLabel(isoDate: string): string {
  return "FY" + isoDate.slice(2, 4);
}
