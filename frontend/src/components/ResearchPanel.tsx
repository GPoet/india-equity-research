"use client";

import { useEffect, useRef, useState } from "react";

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
  const [starting, setStarting] = useState(false);
  const [tick, setTick] = useState(0); // bumping it re-reads the job status
  const [failures, setFailures] = useState(0);
  const lastStatus = useRef<ResearchState["status"] | null>(null);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    api.research(symbol).then(
      (s) => {
        if (!live) return;
        setState(s);
        lastStatus.current = s.status;
        setFailures(0);
        setError(null);
        if (s.status === "running" || s.status === "queued") timer = setTimeout(() => setTick((t) => t + 1), POLL_MS);
      },
      (e) => {
        if (!live) return;
        setError(e instanceof ApiError ? e.message : "Could not load research");
        // Keep checking a job that was in progress, backing off, in case the server restarted.
        const last = lastStatus.current;
        if (last === "running" || last === "queued") {
          timer = setTimeout(() => setTick((t) => t + 1), Math.min(POLL_MS * 2 ** (failures + 1), 60000));
          setFailures((f) => f + 1);
        }
      },
    );
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
    // failures is read only to size the back-off; changing it must not re-poll
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, tick]);

  async function start(force: boolean) {
    setError(null);
    setStarting(true);
    try {
      const next = await api.startResearch(symbol, force);
      lastStatus.current = next.status;
      setState(next);
      setTick((t) => t + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start research");
    } finally {
      setStarting(false);
    }
  }

  const busy = state?.status === "running" || state?.status === "queued";
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
          <button className="primary" onClick={() => start(state.status === "failed")} disabled={starting}
            style={{ marginTop: "0.75rem" }}>
            {starting ? "Starting…" : `Research ${symbol}`}
          </button>
        </>
      )}
      {state?.status === "queued" && <p className="status">Waiting for another company&apos;s research to finish first.</p>}
      {state?.status === "running" && <p className="status">Researching. Reading filings and searching the web…</p>}
      {state?.status === "done" && !busy && <ResearchBody state={state} onRefresh={() => start(true)} refreshing={starting} />}
    </section>
  );
}

function ResearchBody({
  state,
  onRefresh,
  refreshing,
}: {
  state: Extract<ResearchState, { status: "done" }>;
  onRefresh: () => void;
  refreshing: boolean;
}) {
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
        <button className="link" onClick={onRefresh} disabled={refreshing}>Research again</button>
      </p>
      {state.data.warnings?.map((w, i) => <p key={`${i}-${w}`} className="error">{w}</p>)}
      <p className="prose">{r.summary}</p>
      <h3 style={{ margin: "1.5rem 0 0.5rem" }}>Latest results</h3>
      <p className="prose small">{r.latest_results}</p>
      <h3 style={{ margin: "1.5rem 0 0.5rem" }}>What is moving the company</h3>
      {catalysts.length === 0 && <p className="muted">No sourced catalysts found.</p>}
      {catalysts.map((c, i) => <CatalystItem key={`${i}-${c.title}`} c={c} />)}
      {r.regulation.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.5rem" }}>Regulation and policy</h3>
          {r.regulation.map((g, i) => (
            <div key={`${i}-${g.title}`} className={`catalyst ${g.direction}`}>
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
            {[...r.risks].sort((a, b) => b.severity - a.severity).map((k, i) => (
              <li key={`${i}-${k.title}`}>
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
            {r.events.map((e, i) => <li key={`${i}-${e.event}`}>{e.date ?? "Date not announced"}: {e.event}</li>)}
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
          <ul className="small muted">{r.data_gaps.map((g, i) => <li key={`${i}-${g}`}>{g}</li>)}</ul>
        </details>
      )}
    </>
  );
}
