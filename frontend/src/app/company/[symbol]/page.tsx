import type { Metadata } from "next";

import { CompanyView } from "@/components/CompanyView";
import { StaticCompanyPage } from "@/components/StaticCompanyPage";

type Props = { params: Promise<{ symbol: string }> };

const isStatic = process.env.NEXT_PUBLIC_STATIC === "1";

// Hosted site: one shell page; Cloudflare rewrites every /company/<symbol> to it (public/_redirects)
// and the page reads the symbol from the address bar.
export function generateStaticParams() {
  return isStatic ? [{ symbol: "_" }] : [];
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { symbol } = await params;
  return { title: isStatic ? "Company, Equity desk" : `${decodeURIComponent(symbol).toUpperCase()}, Equity desk` };
}

export default async function CompanyPage({ params }: Props) {
  if (isStatic) return <StaticCompanyPage />;
  const { symbol } = await params;
  const sym = decodeURIComponent(symbol).toUpperCase();
  return <CompanyView key={sym} symbol={sym} />;
}
