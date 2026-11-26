"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { CompanyView } from "@/components/CompanyView";

export function StaticCompanyPage() {
  const path = usePathname();
  const sym = decodeURIComponent(path.split("/").filter(Boolean)[1] ?? "").toUpperCase();
  useEffect(() => {
    if (sym) document.title = `${sym}, Equity desk`;
  }, [sym]);
  if (!sym || sym === "_") return <p className="muted">Search for a company above.</p>;
  return <CompanyView key={sym} symbol={sym} />;
}
