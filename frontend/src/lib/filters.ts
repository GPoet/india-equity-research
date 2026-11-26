// Filters for the market pages, shared by the picks and every list, remembered in this browser.
import { useSyncExternalStore } from "react";

export type Board = "main" | "sme" | "bse";
export type ValuationBucket = "under" | "fair" | "over" | "none";

export type Filters = {
  boards: Record<Board, boolean>;
  penny: 0 | 10 | 20 | 50; // hide stocks priced under this many rupees (0 = show all)
  hideThin: boolean; // hide stocks trading under Rs 1 crore a day
  valuation: Record<ValuationBucket, boolean>;
  hideRed: boolean; // hide stocks with red flags from the investor checks
};

export const DEFAULT_FILTERS: Filters = {
  boards: { main: true, sme: true, bse: true },
  penny: 0,
  hideThin: false,
  valuation: { under: true, fair: true, over: true, none: true },
  hideRed: true,
};

export const THIN = 1e7;
const KEY = "eqd-filters-v1";
// NSE SME series SM/ST/SZ; BSE SME platform groups M/MT.
const NSE_SME = new Set(["SM", "ST", "SZ"]);
const BSE_SME = new Set(["M", "MT"]);

export type Filterable = {
  symbol: string;
  key?: string;
  exchange?: string;
  series?: string;
  price?: number;
  close?: number;
  turnover?: number;
  signal?: string | null;
  red?: boolean;
  red_flags?: string[];
};

export function boardOf(r: Filterable): Board {
  const bse = r.exchange === "BSE" || (r.key ?? r.symbol).startsWith("BSE:");
  const series = (r.series ?? "").toUpperCase();
  if (bse) return BSE_SME.has(series) ? "sme" : "bse";
  return NSE_SME.has(series) ? "sme" : "main";
}

export function valuationOf(r: Filterable): ValuationBucket {
  if (r.signal === "Undervalued") return "under";
  if (r.signal === "Fairly valued") return "fair";
  if (r.signal === "Overvalued") return "over";
  return "none"; // not valued, not enough data, or not scanned yet
}

export function passes(r: Filterable, f: Filters): boolean {
  if (!f.boards[boardOf(r)]) return false;
  const price = r.price ?? r.close;
  if (f.penny && price !== undefined && price < f.penny) return false;
  if (f.hideThin && (r.turnover ?? 0) < THIN) return false;
  if (!f.valuation[valuationOf(r)]) return false;
  if (f.hideRed && (r.red || (r.red_flags?.length ?? 0) > 0)) return false;
  return true;
}

export function isDefault(f: Filters): boolean {
  return JSON.stringify(f) === JSON.stringify(DEFAULT_FILTERS);
}

// A tiny store over localStorage so every component sees the same filters without a mismatch
// between the prerendered page (defaults) and the browser (saved choice).
let current: Filters | null = null;
const listeners = new Set<() => void>();

function read(): Filters {
  if (current) return current;
  try {
    const saved = JSON.parse(window.localStorage.getItem(KEY) ?? "null");
    current = saved ? { ...DEFAULT_FILTERS, ...saved,
      boards: { ...DEFAULT_FILTERS.boards, ...saved.boards },
      valuation: { ...DEFAULT_FILTERS.valuation, ...saved.valuation } } : DEFAULT_FILTERS;
  } catch {
    current = DEFAULT_FILTERS; // storage blocked: defaults, nothing saved
  }
  return current as Filters;
}

export function setFilters(next: Filters): void {
  current = next;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage blocked: the choice lasts until the page is closed */
  }
  listeners.forEach((l) => l());
}

export function useFilters(): Filters {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    read,
    () => DEFAULT_FILTERS,
  );
}
