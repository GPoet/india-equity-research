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

export type SignalSummary = {
  signal: string;
  horizon: string;
  n: number;
  pending: number;
  hit_rate: number | null;
  mean_excess: number | null;
  median_excess: number | null;
};

export type Score = { outcome: string; excess: number | null; stock_return?: number; index_return?: number };

export type JournalEntry = {
  id: number;
  day: string;
  symbol: string;
  price: number;
  signal: string;
  confidence: string;
  mid: number | null;
  upside: number | null;
  scores: Record<string, Score>;
};

export type Journal = { as_of: string; entries: JournalEntry[]; summary: SignalSummary[]; engine_version: string };

export type Backtest = {
  run_at: string;
  engine_version: string;
  start: string;
  end: string;
  universe: string;
  symbols: number;
  limitations: string[];
  summary: {
    observations: number;
    usable?: number;
    excluded?: Record<string, number>;
    base_rate?: Record<string, number | null>;
    by_signal: SignalSummary[];
    upside_vs_return: Record<string, { n: number; spearman: number | null; top_quintile_excess: number | null; bottom_quintile_excess: number | null }>;
  };
};

export type HorizonForecast = {
  horizon: string;
  days: number;
  median: number;
  band50: [number, number];
  band80: [number, number];
  p_up: number;
  p_beat_nifty: number;
  expected_excess: number;
  results_in_window: boolean;
  target_date: string;
  lean: string;
};

export type ForecastTest = {
  n: number;
  dates?: number;
  rank_ic?: number | null;
  rank_ic_t?: number | null;
  top_minus_bottom?: number | null;
  direction_right?: number;
  base_rate_beat_nifty?: number;
  coverage_80?: number;
};

export type Forecast =
  | { status: "not_fitted" | "no_data"; error: string }
  | {
      status: "ok";
      price: number;
      price_as_of: string;
      horizons: HorizonForecast[];
      inputs: { mom_12_1: number; rev_1m: number; surprise: number | null; value: number | null; next_results_est: string | null };
      model: { fitted_on: string; tested_on: string; test: Record<string, ForecastTest>; has_edge: Record<string, boolean> };
    };

export type Sentiment = {
  symbol: string;
  report: {
    overall: "bullish" | "neutral" | "bearish" | "mixed";
    score: number;
    summary: string;
    volume: string;
    volume_note: string;
    themes: { theme: string; stance: string; detail: string; post_urls: string[] }[];
    notable_posts: { url: string; author: string; author_type: string; stance: string; summary: string }[];
    pump_risk: { level: "low" | "medium" | "high"; signals: string[] };
    data_gaps: string[];
  };
  meta: { as_of: string; posts_fetched: number; cost_usd: number; month_spend_usd?: number; window_days: number };
};

export type SentimentState =
  | { status: "disabled"; error: string }
  | { status: "none" }
  | { status: "queued" }
  | { status: "running" }
  | { status: "done"; data: Sentiment; cached?: boolean }
  | { status: "failed"; error: string; kind: string };

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
  forecast: (s: string) => call<Forecast>(`/api/company/${encodeURIComponent(s)}/forecast`),
  sentiment: (s: string) => call<SentimentState>(`/api/company/${encodeURIComponent(s)}/sentiment`),
  startSentiment: (s: string, force = false) =>
    call<SentimentState>(`/api/company/${encodeURIComponent(s)}/sentiment${force ? "?force=true" : ""}`, {
      method: "POST",
      headers: { "X-Equity-Desk": "1" },
    }),
  journal: () => call<Journal>(`/api/journal`),
  backtest: () => call<Backtest>(`/api/backtest`),
  research: (s: string) => call<ResearchState>(`/api/company/${encodeURIComponent(s)}/research`),
  // The custom header lets the API refuse cross-site requests (see backend app/api.py).
  startResearch: (s: string, force = false) =>
    call<ResearchState>(`/api/company/${encodeURIComponent(s)}/research${force ? "?force=true" : ""}`, {
      method: "POST",
      headers: { "X-Equity-Desk": "1" },
    }),
};
