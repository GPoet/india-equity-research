import { SearchBox } from "@/components/SearchBox";

export default function Home() {
  return (
    <div className="home">
      <h1>What is this company worth, and what is moving it?</h1>
      <p className="lede">
        Fair value from Buffett, Graham, Lynch and cash-flow models, built from the company&apos;s own NSE filings,
        with news, regulation and its sector alongside.
      </p>
      <SearchBox />
    </div>
  );
}
