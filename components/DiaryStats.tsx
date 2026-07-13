import { CircleDollarSign, Percent, TrendingUp, Trophy, Wallet } from "lucide-react";
import type { DiarySummary } from "@/lib/diary";
import { formatCurrency, formatPct } from "@/lib/utils";
import StatTile from "./StatTile";

export default function DiaryStats({ summary }: { summary: DiarySummary }) {
  const positive = summary.cumulativeReturnPct >= 0;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <StatTile label="Portfolio Value" value={formatCurrency(summary.currentValue)} icon={<Wallet size={14} />} />
      <StatTile
        label="Cumulative Return"
        value={formatPct(summary.cumulativeReturnPct, { signed: true })}
        icon={<TrendingUp size={14} />}
        tone={positive ? "good" : "bad"}
      />
      <StatTile
        label="Realized P&L"
        value={formatCurrency(summary.realizedProfitTotal)}
        icon={<CircleDollarSign size={14} />}
        tone={summary.realizedProfitTotal >= 0 ? "good" : "bad"}
      />
      <StatTile
        label="Unrealized P&L"
        value={formatCurrency(summary.unrealizedProfitTotal)}
        icon={<CircleDollarSign size={14} />}
        tone={summary.unrealizedProfitTotal >= 0 ? "good" : "bad"}
      />
      <StatTile label="Win Rate (closed)" value={`${summary.winRatePct.toFixed(1)}%`} icon={<Percent size={14} />} />
      <StatTile
        label="Trades (closed / open)"
        value={`${summary.closedTrades} / ${summary.openTrades}${
          summary.currentStreak ? ` · ${summary.currentStreak.type}${summary.currentStreak.length}` : ""
        }`}
        icon={<Trophy size={14} />}
      />
    </div>
  );
}
