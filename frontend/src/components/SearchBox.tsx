"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { api, ApiError, type Resolution } from "@/lib/api";

export function SearchBox({ compact = false }: { compact?: boolean }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Resolution | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.resolve(q);
      if (res.match) {
        router.push(`/company/${encodeURIComponent(res.match.symbol)}`);
        setQuery("");
      } else {
        setResult(res);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed");
    } finally {
      setBusy(false);
    }
  }

  function pick(symbol: string) {
    setResult(null);
    setQuery("");
    router.push(`/company/${encodeURIComponent(symbol)}`);
  }

  return (
    <form className="search" onSubmit={submit} role="search">
      <label htmlFor={compact ? "q-top" : "q-home"} className="visually-hidden" style={{ position: "absolute", left: -9999 }}>
        Company name, NSE ticker or link
      </label>
      <input
        id={compact ? "q-top" : "q-home"}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={compact ? "Company, ticker or link" : "Try TCS, HDFC Bank, or paste a Screener or Moneycontrol link"}
        autoComplete="off"
        disabled={busy}
      />
      {error && <p className="search-hint" role="alert">{error}</p>}
      {result && result.candidates.length > 0 && (
        <>
          <p className="search-hint">More than one company fits. Pick one:</p>
          <ul className="candidates">
            {result.candidates.map((c) => (
              <li key={c.symbol}>
                <button type="button" onClick={() => pick(c.symbol)}>
                  {c.name} <span>{c.symbol}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {result && result.candidates.length === 0 && (
        <p className="search-hint">No NSE-listed company matches that. Check the spelling or use the ticker.</p>
      )}
    </form>
  );
}
