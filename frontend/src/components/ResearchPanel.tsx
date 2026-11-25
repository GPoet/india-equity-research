"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type Catalyst, type ResearchState } from "@/lib/api";

const POLL_MS = 4000;

function CatalystItem({ c }: { c: Catalyst }) {
  return (
    <div className={`catalyst ${c.direction}`}>
      <strong>{c.title}</strong>
      <div className="meta">
        {c.direction === "tailwind" ? "Tailwind" : c.direction === "headwind" ? "Headwind" : "Mixed"}, importance {c.materiality} of 5
        {c.date && <>, {c.date}</>}.{" "}
        <a href={c.source_url} target="_blank" rel="noreferrer noopener">
          {c.source_name}
        </a>
      </div>
      <p>{c.detail}</p>
    </div>
  );
}

export function ResearchPanel({ symbol }: { symbol: string }) {
  const [state, setState] = useState<ResearchState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0); // bumping it re-reads the job status

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    api.research(symbol).then(
      (s) => {
        if (!live) return;
        setState(s);
        if (s.status === "running") timer = setTimeout(() => setTick((t) => t + 1), POLL_MS);
      },
      (e) => live && setError(e instanceof ApiError ? e.message : "Could not load research"),
    );
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [symbol, tick]);

  async function start() {
    setError(null);
    try {
      setState(await api.startResearch(symbol));
      setTick((t) => t + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start research");
    }
  }

  const running = state?.status === "running";
  return (
    <section aria-live="polite">
      <h2>News, filings and regulation</h2>
      <p className="note">
        Claude reads the company&apos;s NSE filings and searches the web. Every item links to its source. Takes 1 to 3 minutes.
      </p>
      {error && <p className="error">{error}</p>}
      {(state?.status === "none" || state?.status === "failed") && (
        <>
          {state.status === "failed" && <p className="error">Research failed: {state.error}</p>}
          <button className="primary" onClick={start} style={{ marginTop: "0.75rem" }}>
            Research {symbol}
          </button>
        </>
      )}
      {running && <p className="status">Researching. Reading filings and searching the web…</p>}
      {state?.status === "done" && <ResearchBody state={state} onRefresh={start} />}
    </section>
  );
}

function ResearchBody({ state, onRefresh }: { state: Extract<ResearchState, { status: "done" }>; onRefresh: () => void }) {
  const r = state.data.report;
  const m = state.data.meta;
  const order = { tailwind: 0, mixed: 1, headwind: 2 } as const;
  const catalysts = [...r.catalysts].sort((a, b) => b.materiality - a.materiality || order[a.direction] - order[b.direction]);
  const dropped = Object.values(state.data.dropped).reduce((a, b) => a + b, 0);
  return (
    <>
      <p className="small muted" style={{ marginBottom: "1rem" }}>
        Researched {m.as_of} with Claude {m.model}, {m.documents_given ?? 0} NSE filings read.{" "}
        {dropped > 0 && <>{dropped} unsourced or unverifiable items removed. </>}
        <button className="link" onClick={onRefresh}>Research again</button>
      </p>
      {state.data.warnings?.map((w) => <p key={w} className="error">{w}</p>)}
      <p className="prose">{r.summary}</p>
      <h3 style={{ margin: "1.5rem 0 0.5rem" }}>Latest results</h3>
      <p className="prose small">{r.latest_results}</p>
      <h3 style={{ margin: "1.5rem 0 0.5rem" }}>What is moving the company</h3>
      {catalysts.length === 0 && <p className="muted">No sourced catalysts found.</p>}
      {catalysts.map((c) => <CatalystItem key={c.source_url + c.title} c={c} />)}
      {r.regulation.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.5rem" }}>Regulation and policy</h3>
          {r.regulation.map((g) => (
            <div key={g.source_url + g.title} className={`catalyst ${g.direction}`}>
              <strong>{g.title}</strong>
              <div className="meta">
                {g.regulator}, {g.status}
                {g.effective_date && <>, effective {g.effective_date}</>}.{" "}
                <a href={g.source_url} target="_blank" rel="noreferrer noopener">Source</a>
              </div>
              <p>{g.detail}</p>
            </div>
          ))}
        </>
      )}
      {r.risks.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.5rem" }}>Risks</h3>
          <ul className="small">
            {[...r.risks].sort((a, b) => b.severity - a.severity).map((k) => (
              <li key={k.title}>
                <strong>{k.title}.</strong> {k.detail}{" "}
                {k.source_url && <a href={k.source_url} target="_blank" rel="noreferrer noopener">Source</a>}
              </li>
            ))}
          </ul>
        </>
      )}
      {r.events.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.5rem" }}>Coming up</h3>
          <ul className="small">
            {r.events.map((e) => <li key={e.event}>{e.date ?? "Date not announced"}: {e.event}</li>)}
          </ul>
        </>
      )}
      <h3 style={{ margin: "1.5rem 0 0.5rem" }}>Bull case</h3>
      <p className="prose small">{r.bull_case}</p>
      <h3 style={{ margin: "1rem 0 0.5rem" }}>Bear case</h3>
      <p className="prose small">{r.bear_case}</p>
      {r.data_gaps.length > 0 && (
        <details style={{ marginTop: "1rem" }}>
          <summary>What could not be verified ({r.data_gaps.length})</summary>
          <ul className="small muted">{r.data_gaps.map((g) => <li key={g}>{g}</li>)}</ul>
        </details>
      )}
    </>
  );
}
