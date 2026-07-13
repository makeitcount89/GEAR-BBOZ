import { CircleDollarSign, LineChart, Percent, Scale, TrendingUp, Trophy, Wallet } from "lucide-react";
import type { PortfolioMetrics } from "@/lib/types";
import { formatCurrency, formatPct } from "@/lib/utils";
import StatTile from "./StatTile";

export default function PortfolioStats({ portfolio }: { portfolio: PortfolioMetrics }) {
  const positive = portfolio.totalReturnPct >= 0;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
      <StatTile
        label="Portfolio Value"
        value={formatCurrency(portfolio.currentValue)}
        icon={<Wallet size={14} />}
      />
      <StatTile
        label="Total Return"
        value={formatPct(portfolio.totalReturnPct, { signed: true })}
        icon={<TrendingUp size={14} />}
        tone={positive ? "good" : "bad"}
      />
      <StatTile
        label="Win Rate (traded)"
        value={`${portfolio.winRatePct.toFixed(1)}%`}
        icon={<Percent size={14} />}
      />
      <StatTile
        label="Trades / Streak"
        value={
          portfolio.totalTrades === 0
            ? "0"
            : `${portfolio.wins + portfolio.losses} · ${portfolio.currentStreak?.type ?? "–"}${portfolio.currentStreak?.length ?? ""}`
        }
        icon={<Trophy size={14} />}
      />
      <StatTile
        label="Cash Sessions"
        value={`${portfolio.cashSessions} / ${portfolio.totalTrades}`}
        icon={<CircleDollarSign size={14} />}
      />
      <StatTile
        label="vs Buy & Hold GEAR"
        value={formatPct(portfolio.buyHoldGearReturnPct, { signed: true })}
        icon={<Scale size={14} />}
        tone={portfolio.beatBuyHoldGear ? "good" : "bad"}
      />
      <StatTile
        label="vs Buy & Hold ^AXJO"
        value={formatPct(portfolio.buyHoldAxjoReturnPct, { signed: true })}
        icon={<LineChart size={14} />}
        tone={portfolio.beatBuyHoldAxjo ? "good" : "bad"}
      />
    </div>
  );
}
