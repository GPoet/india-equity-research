import { DailyScan } from "@/components/DailyScan";
import { MarketOverview } from "@/components/MarketOverview";

export default function Home() {
  return (
    <div className="home">
      <h1>Markets</h1>
      <DailyScan />
      <MarketOverview />
    </div>
  );
}
