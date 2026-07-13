import { Check, History, X } from "lucide-react";
import type { Validation } from "@/lib/types";
import { cn, formatDate, formatPct } from "@/lib/utils";

export default function ValidationWindows({
  validation,
  holdoutWindowWeeks,
}: {
  validation: Validation | undefined;
  holdoutWindowWeeks?: number;
}) {
  const windows = validation?.windows ?? [];
  const summary = validation?.summary;

  if (windows.length === 0) {
    return null;
  }

  return (
    <div className="rounded-xl border border-base-700 bg-base-850 p-5">
      <h2 className="flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
        <History size={16} className="text-[var(--series-profit)]" />
        Validation Across Historical Windows
        <span className="ml-1 rounded-full bg-base-800 px-2 py-0.5 text-xs text-[var(--text-muted)]">
          {windows.length} window{windows.length === 1 ? "" : "s"}
        </span>
      </h2>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        Each row is an independent $500-seeded {holdoutWindowWeeks ?? "—"}-week walk-forward run, most recent first —
        a single window is too small a sample to trust on its own, so this checks whether the edge holds up across
        several non-overlapping periods.
      </p>

      {summary && windows.length > 1 && (
        <dl className="mt-4 grid grid-cols-2 gap-4 border-t border-base-700 pt-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
          <div>
            <dt className="text-xs text-[var(--text-muted)]">Mean Win Rate (± stddev)</dt>
            <dd className="tabular font-medium">
              {summary.meanWinRatePct?.toFixed(1)}% <span className="text-[var(--text-muted)]">± {summary.stdDevWinRatePct?.toFixed(1)}</span>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--text-muted)]">Mean Return (± stddev)</dt>
            <dd className="tabular font-medium">
              {formatPct(summary.meanTotalReturnPct ?? 0, { signed: true })}{" "}
              <span className="text-[var(--text-muted)]">± {summary.stdDevTotalReturnPct?.toFixed(1)}</span>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--text-muted)]">Mean B&amp;H GEAR Return</dt>
            <dd className="tabular font-medium">{formatPct(summary.meanBuyHoldGearReturnPct ?? 0, { signed: true })}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--text-muted)]">Windows Beating B&amp;H GEAR</dt>
            <dd
              className={cn(
                "tabular font-medium",
                (summary.windowsBeatingBuyHoldGear ?? 0) * 2 >= windows.length ? "text-[var(--status-good)]" : "text-[var(--status-critical)]"
              )}
            >
              {summary.windowsBeatingBuyHoldGear ?? 0} / {windows.length}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--text-muted)]">Mean B&amp;H ^AXJO Return</dt>
            <dd className="tabular font-medium">{formatPct(summary.meanBuyHoldAxjoReturnPct ?? 0, { signed: true })}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--text-muted)]">Windows Beating B&amp;H ^AXJO</dt>
            <dd
              className={cn(
                "tabular font-medium",
                (summary.windowsBeatingBuyHoldAxjo ?? 0) * 2 >= windows.length ? "text-[var(--status-good)]" : "text-[var(--status-critical)]"
              )}
            >
              {summary.windowsBeatingBuyHoldAxjo ?? 0} / {windows.length}
            </dd>
          </div>
        </dl>
      )}

      <div className="mt-4 overflow-auto rounded-lg border border-base-700">
        <table className="w-full min-w-[1120px] border-collapse text-sm">
          <thead className="bg-base-800 text-xs text-[var(--text-muted)]">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Window</th>
              <th className="px-3 py-2 text-left font-medium">Period</th>
              <th className="px-3 py-2 text-right font-medium">Trades</th>
              <th className="px-3 py-2 text-right font-medium">Cash</th>
              <th className="px-3 py-2 text-right font-medium">Win Rate</th>
              <th className="px-3 py-2 text-right font-medium">GEAR</th>
              <th className="px-3 py-2 text-right font-medium">BBOZ</th>
              <th className="px-3 py-2 text-right font-medium">Return</th>
              <th className="px-3 py-2 text-right font-medium">B&amp;H GEAR</th>
              <th className="px-3 py-2 text-center font-medium">Beats B&amp;H GEAR</th>
              <th className="px-3 py-2 text-right font-medium">B&amp;H ^AXJO</th>
              <th className="px-3 py-2 text-center font-medium">Beats B&amp;H ^AXJO</th>
            </tr>
          </thead>
          <tbody>
            {windows.map((w) => (
              <tr key={w.windowIndex} className={cn("border-t border-base-700", w.windowIndex === 0 && "bg-base-800/40")}>
                <td className="px-3 py-2 font-medium">{w.windowIndex === 0 ? "Current" : `${w.windowIndex} back`}</td>
                <td className="px-3 py-2 text-[var(--text-secondary)]">
                  {formatDate(w.startDate)} – {formatDate(w.endDate)}
                </td>
                <td className="px-3 py-2 text-right tabular">{w.wins + w.losses}</td>
                <td className="px-3 py-2 text-right tabular">{w.cashSessions}</td>
                <td className="px-3 py-2 text-right tabular font-medium">{w.winRatePct.toFixed(1)}%</td>
                <td className="px-3 py-2 text-right tabular text-long">
                  {w.assetBreakdown.GEAR.trades ? `${w.assetBreakdown.GEAR.trades} (${w.assetBreakdown.GEAR.winRatePct.toFixed(0)}%)` : "—"}
                </td>
                <td className="px-3 py-2 text-right tabular text-short">
                  {w.assetBreakdown.BBOZ.trades ? `${w.assetBreakdown.BBOZ.trades} (${w.assetBreakdown.BBOZ.winRatePct.toFixed(0)}%)` : "—"}
                </td>
                <td
                  className={cn(
                    "px-3 py-2 text-right tabular font-medium",
                    w.totalReturnPct >= 0 ? "text-[var(--status-good)]" : "text-[var(--status-critical)]"
                  )}
                >
                  {formatPct(w.totalReturnPct, { signed: true })}
                </td>
                <td className="px-3 py-2 text-right tabular text-[var(--text-secondary)]">
                  {formatPct(w.buyHoldGearReturnPct, { signed: true })}
                </td>
                <td className="px-3 py-2">
                  <div className="flex justify-center">
                    {w.beatBuyHoldGear ? (
                      <Check size={15} className="text-[var(--status-good)]" />
                    ) : (
                      <X size={15} className="text-[var(--status-critical)]" />
                    )}
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular text-[var(--text-secondary)]">
                  {formatPct(w.buyHoldAxjoReturnPct, { signed: true })}
                </td>
                <td className="px-3 py-2">
                  <div className="flex justify-center">
                    {w.beatBuyHoldAxjo ? (
                      <Check size={15} className="text-[var(--status-good)]" />
                    ) : (
                      <X size={15} className="text-[var(--status-critical)]" />
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
