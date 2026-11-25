"use client";

import type { Period } from "@/lib/api";

const LABELS: Record<Period, string> = { day: "Day", week: "Week", month: "Month" };

export function PeriodSwitch({ value, onChange, label }: { value: Period; onChange: (p: Period) => void; label: string }) {
  return (
    <div className="switch" role="group" aria-label={label}>
      {(Object.keys(LABELS) as Period[]).map((p) => (
        <button key={p} type="button" aria-pressed={value === p} onClick={() => onChange(p)}>
          {LABELS[p]}
        </button>
      ))}
    </div>
  );
}
