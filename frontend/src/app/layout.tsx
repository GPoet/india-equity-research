import type { Metadata } from "next";
import { Mukta } from "next/font/google";
import Link from "next/link";

import { SearchBox } from "@/components/SearchBox";

import "./globals.css";

// Mukta, from the Indian foundry Ek Type: one family, three weights.
const mukta = Mukta({ subsets: ["latin"], weight: ["400", "600", "800"] });

export const metadata: Metadata = {
  title: "Equity desk",
  description: "Personal research on NSE-listed companies: value, filings, news and sectors.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className={mukta.className}>
      <body>
        <div className="frame">
          <header className="topbar">
            <Link href="/" className="brand">
              Equity desk
            </Link>
            <SearchBox compact />
            <nav aria-label="Main">
              <Link href="/sectors">Sectors</Link>
              <Link href="/track">Track record</Link>
            </nav>
          </header>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
