import type { Metadata } from "next";

import { CompanyView } from "@/components/CompanyView";

type Props = { params: Promise<{ symbol: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { symbol } = await params;
  return { title: `${decodeURIComponent(symbol).toUpperCase()}, Equity desk` };
}

export default async function CompanyPage({ params }: Props) {
  const { symbol } = await params;
  const sym = decodeURIComponent(symbol).toUpperCase();
  return <CompanyView key={sym} symbol={sym} />;
}
