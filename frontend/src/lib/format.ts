// Number formatting pinned to Indian conventions (lakh/crore grouping), independent of the
// browser's locale.
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const CRORE = 1e7;

// Negative amounts read "−₹1,234", never "₹-1,234".
function signed(abs: string, negative: boolean): string {
  return (negative ? "−₹" : "₹") + abs;
}

export function rupees(x: number | null | undefined, decimals = false): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "–";
  return signed((decimals ? inr2 : inr).format(Math.abs(x)), x < 0);
}

export function crore(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "–";
  return signed(inr.format(Math.abs(x) / CRORE), x < 0) + " cr";
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

// Share counts in Indian units: 45,300 / 12.3 L / 1.24 Cr.
export function shares(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "–";
  if (x >= CRORE) return (x / CRORE).toFixed(2) + " Cr";
  if (x >= 1e5) return (x / 1e5).toFixed(1) + " L";
  return inr.format(x);
}
