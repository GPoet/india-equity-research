"use client";

import { DailyScan } from "@/components/DailyScan";
import { FilterBar } from "@/components/FilterBar";
import { MarketOverview } from "@/components/MarketOverview";
import { useFilters } from "@/lib/filters";

// The market pages share one set of filters: the bar sets them, the picks and every list obey.
export function MarketsView() {
  const filters = useFilters();
  return (
    <>
      <FilterBar filters={filters} />
      <DailyScan filters={filters} />
      <MarketOverview filters={filters} />
    </>
  );
}
