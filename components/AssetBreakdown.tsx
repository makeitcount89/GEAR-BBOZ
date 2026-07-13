import { ArrowDownRight, ArrowUpRight, Scale } from "lucide-react";
import type { AssetBreakdown as AssetBreakdownData } from "@/lib/types";
import { cn, formatCurrency, formatPct } from "@/lib/utils";

const ASSET_PRESENTATION = {
  GEAR: { label: "GEAR", subtitle: "GEAR.AX (Long Geared)", badge: "bg-long-muted text-long", icon: <ArrowUpRight size={16} /> },
  BBOZ: { label: "BBOZ", subtitle: "BBOZ.AX (Short Geared)", badge: "bg-short-muted text-short", icon: <ArrowDownRight size={16} /> },
} as const;

export default function AssetBreakdown({ breakdown }: { breakdown: AssetBreakdownData }) {
  const assets = ["GEAR", "BBOZ"] as const;
  const anyTrades = assets.some((a) => breakdown[a].trades > 0);

  return (
    <div className="rounded-xl border border-base-700 bg-base-850 p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
        <Scale size={16} className="text-[var(--series-profit)]" />
        GEAR vs BBOZ — Accuracy &amp; Profit Contribution
      </h2>

      {!anyTrades ? (
        <p className="text-sm text-[var(--text-secondary)]">No directional trades in this window yet.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {assets.map((asset) => {
            const b = breakdown[asset];
            const presentation = ASSET_PRESENTATION[asset];
            const positive = b.dollarPnl >= 0;
            return (
              <div key={asset} className="rounded-lg border border-base-700 bg-base-800/60 p-4">
                <div className="flex items-center justify-between">
                  <span className={cn("flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold", presentation.badge)}>
                    {presentation.icon}
                    {presentation.label}
                  </span>
                  <span className="text-xs text-[var(--text-muted)]">{presentation.subtitle}</span>
                </div>
                <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
                  <div>
                    <dt className="text-xs text-[var(--text-muted)]">Trades</dt>
                    <dd className="tabular font-medium">
                      {b.trades} <span className="text-xs text-[var(--text-muted)]">({b.wins}W / {b.losses}L)</span>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--text-muted)]">Win rate</dt>
                    <dd className="tabular font-medium">{b.trades ? `${b.winRatePct.toFixed(1)}%` : "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--text-muted)]">Contribution</dt>
                    <dd className={cn("tabular font-medium", positive ? "text-[var(--status-good)]" : "text-[var(--status-critical)]")}>
                      {b.trades ? `${formatCurrency(b.dollarPnl)} (${formatPct(b.contributionPct, { signed: true })})` : "—"}
                    </dd>
                  </div>
                </dl>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
