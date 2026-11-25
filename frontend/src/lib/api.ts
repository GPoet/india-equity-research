// Typed access to the FastAPI backend (proxied at /api by next.config.ts).

export type Lens = {
  key: string;
  name: string;
  school: string;
  kind: "value" | "score" | "screen" | "metric";
  applicable: boolean;
  value: number | null;
  verdict: string | null;
  summary: string;
  inputs: Record<string, number | string | null>;
  reason: string | null;
};

export type Blend = {
  low: number | null;
  mid: number | null;
  high: number | null;
  buy_below: number | null;
  signal: string;
  confidence: string;
  upside: number | null;
  used: Record<string, number>;
  reasons: string[];
  red_flags: string[];
};

export type Valuation = {
  symbol: string;
  price: number;
  price_as_of: string;
  company_type: string;
  lenses: Lens[];
  implied_growth: Lens;
  result: Blend;
  assumptions: Record<string, unknown> & {
    cost_of_equity: number;
    wacc: number | null;
    growth: number | null;
    beta: number;
    market_cap: number | null;
    eps_ttm: number | null;
    notes: string[];
    market_inputs_as_of: string;
  };
  warnings: string[];
};

export type YearRow = {
  fy_end: string;
  revenue: number | null;
  ebitda: number | null;
  profit: number | null;
  eps: number | null;
  cfo: number | null;
  nii: number | null;
  source: string;
};

export type Company = {
  symbol: string;
  name: string;
  industry: string | null;
  sector_key: string | null;
  valuation: Valuation;
  financials: { years: YearRow[]; quarters: { period_end: string; revenue: number | null; profit: number | null }[] };
};

export type SectorStat = {
  key: string;
  label: string;
  stance: string;
  rank: number;
  of: number;
  rs_3m: number | null;
  rs_6m: number | null;
  vs_200dma: number | null;
  pe: number | null;
  pe_premium: number | null;
};

export type SectorPicture = {
  industry: string | null;
  sector_key: string | null;
  picture: {
    as_of: string;
    sector: SectorStat | null;
    related: { stat: SectorStat; why: string; correlation: number | null; basis: string }[];
    strongest: SectorStat[];
    notes: string[];
  };
};

export type Catalyst = {
  title: string;
  detail: string;
  kind: string;
  direction: "tailwind" | "headwind" | "mixed";
  materiality: number;
  horizon: string;
  date: string | null;
  source_url: string;
  source_name: string;
};

export type Research = {
  symbol: string;
  report: {
    summary: string;
    business: string;
    latest_results: string;
    catalysts: Catalyst[];
    regulation: {
      title: string;
      regulator: string;
      status: string;
      effective_date: string | null;
      direction: string;
      detail: string;
      source_url: string;
    }[];
    risks: { title: string; detail: string; severity: number; source_url: string | null }[];
    events: { date: string | null; event: string }[];
    sector_view: { sector: string; stance: string; reasoning: string; source_urls: string[] };
    bull_case: string;
    bear_case: string;
    data_gaps: string[];
  };
  dropped: Record<string, number>;
  meta: { as_of: string; model: string; duration_ms: number | null; tool_calls?: Record<string, number>; documents_given?: number };
  warnings?: string[];
};

export type ResearchState =
  | { status: "none" }
  | { status: "queued" }
  | { status: "running" }
  | { status: "done"; data: Research; cached?: boolean }
  | { status: "failed"; error: string; kind: string };

export type Resolution = {
  match: { symbol: string; name: string } | null;
  candidates: { symbol: string; name: string; score: number }[];
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, "Can't reach the research server. Start it with: uv run python scripts/run_api.py");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status line */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  resolve: (q: string) => call<Resolution>(`/api/resolve?q=${encodeURIComponent(q)}`),
  company: (s: string) => call<Company>(`/api/company/${encodeURIComponent(s)}`),
  prices: (s: string, period = "1y") =>
    call<{ points: { date: string; close: number }[] }>(`/api/company/${encodeURIComponent(s)}/prices?period=${period}`),
  sector: (s: string) => call<SectorPicture>(`/api/company/${encodeURIComponent(s)}/sector`),
  sectors: () => call<{ as_of: string; sectors: SectorStat[] }>(`/api/sectors`),
  research: (s: string) => call<ResearchState>(`/api/company/${encodeURIComponent(s)}/research`),
  // The custom header lets the API refuse cross-site requests (see backend app/api.py).
  startResearch: (s: string, force = false) =>
    call<ResearchState>(`/api/company/${encodeURIComponent(s)}/research${force ? "?force=true" : ""}`, {
      method: "POST",
      headers: { "X-Equity-Desk": "1" },
    }),
};
