"use client";

import { Fragment, useState } from "react";
import { BookOpen, Check, ChevronDown, ChevronRight, X } from "lucide-react";
import type { Asset, GmmaFilters, LedgerRow, PositionAction } from "@/lib/types";
import { cn, formatCurrency, formatDate, formatPct } from "@/lib/utils";

const ASSET_BADGE: Record<Asset, string> = {
  GEAR: "bg-long-muted text-long",
  BBOZ: "bg-short-muted text-short",
  CASH: "bg-base-700 text-[var(--text-secondary)]",
};

const ACTION_LABEL: Record<PositionAction, string> = {
  ENTER: "Enter",
  HOLD: "Hold",
  FLIP: "Flip",
  EXIT: "Exit",
  CASH: "Cash",
};

const ACTION_BADGE: Record<PositionAction, string> = {
  ENTER: "bg-base-700 text-[var(--text-primary)]",
  HOLD: "bg-accent-muted text-accent",
  FLIP: "bg-short-muted text-short",
  EXIT: "bg-base-700 text-[var(--text-muted)]",
  CASH: "bg-base-800 text-[var(--text-muted)]",
};

const FILTER_LABELS: Record<keyof GmmaFilters, string> = {
  trendAlignment: "GMMA trend alignment",
  relativeStrength: "Relative strength",
  liquidity: "Above-average liquidity",
  pullbackNotExtended: "Pullback, not extended",
};

function FilterDots({ filters }: { filters: GmmaFilters }) {
  const keys = Object.keys(filters) as (keyof GmmaFilters)[];
  return (
    <div className="flex items-center gap-1" title={keys.map((k) => `${FILTER_LABELS[k]}: ${filters[k].pass ? "pass" : "fail"}`).join(" · ")}>
      {keys.map((k) => (
        <span
          key={k}
          className={cn("h-2 w-2 rounded-full", filters[k].pass ? "bg-long" : "bg-short")}
        />
      ))}
    </div>
  );
}

export default function LedgerTable({ ledger, holdoutWindowWeeks }: { ledger: LedgerRow[]; holdoutWindowWeeks?: number }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="rounded-xl border border-base-700 bg-base-850 p-5">
      <h2 className="flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
        <BookOpen size={16} className="text-[var(--series-profit)]" />
        Trading Ledger Diary
        <span className="ml-1 rounded-full bg-base-800 px-2 py-0.5 text-xs text-[var(--text-muted)]">
          {ledger.length} rows{holdoutWindowWeeks ? ` · ${holdoutWindowWeeks}-week holdout` : ""}
        </span>
      </h2>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        Click a row to see that session&apos;s raw k-NN call and the 4 confirmation filters behind the action taken.
      </p>

      {ledger.length === 0 ? (
        <p className="mt-6 py-8 text-center text-sm text-[var(--text-secondary)]">
          The ledger populates once the first walk-forward backtest run completes.
        </p>
      ) : (
        <div className="mt-4 max-h-[520px] overflow-auto rounded-lg border border-base-700">
          <table className="w-full min-w-[980px] border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-base-800 text-xs text-[var(--text-muted)]">
              <tr>
                <th className="w-6 px-2 py-2"></th>
                <th className="px-3 py-2 text-left font-medium">Decision</th>
                <th className="px-3 py-2 text-left font-medium">Realization</th>
                <th className="px-3 py-2 text-left font-medium">Allocated</th>
                <th className="px-3 py-2 text-left font-medium">Action</th>
                <th className="px-3 py-2 text-left font-medium">Filters</th>
                <th className="px-3 py-2 text-right font-medium">GEAR Price</th>
                <th className="px-3 py-2 text-right font-medium">BBOZ Price</th>
                <th className="px-3 py-2 text-right font-medium">Interval Return</th>
                <th className="px-3 py-2 text-right font-medium">Portfolio Value</th>
                <th className="px-3 py-2 text-right font-medium">Cumulative</th>
                <th className="px-3 py-2 text-center font-medium">Correct</th>
              </tr>
            </thead>
            <tbody>
              {ledger
                .slice()
                .reverse()
                .map((row) => {
                  const isCash = row.allocatedAsset === "CASH";
                  const positive = row.intervalReturnPct > 0;
                  const isOpen = expanded === row.decisionDate;
                  return (
                    <Fragment key={row.decisionDate}>
                      <tr
                        onClick={() => setExpanded(isOpen ? null : row.decisionDate)}
                        className="cursor-pointer border-t border-base-700 hover:bg-base-800/60"
                      >
                        <td className="px-2 py-2 text-[var(--text-muted)]">
                          {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </td>
                        <td className="px-3 py-2 text-[var(--text-secondary)]">{formatDate(row.decisionDate)}</td>
                        <td className="px-3 py-2 text-[var(--text-secondary)]">{formatDate(row.realizationDate)}</td>
                        <td className="px-3 py-2">
                          <span className={cn("rounded-md px-2 py-0.5 text-xs font-semibold", ASSET_BADGE[row.allocatedAsset])}>
                            {row.allocatedAsset}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <span className={cn("rounded-md px-2 py-0.5 text-xs font-medium", ACTION_BADGE[row.action])}>
                            {ACTION_LABEL[row.action]}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <FilterDots filters={row.filters} />
                        </td>
                        <td className="px-3 py-2 text-right tabular">${row.gearPrice.toFixed(3)}</td>
                        <td className="px-3 py-2 text-right tabular">${row.bbozPrice.toFixed(3)}</td>
                        <td
                          className={cn(
                            "px-3 py-2 text-right tabular font-medium",
                            isCash
                              ? "text-[var(--text-muted)]"
                              : positive
                                ? "text-[var(--status-good)]"
                                : "text-[var(--status-critical)]"
                          )}
                        >
                          {formatPct(row.intervalReturnPct, { signed: true })}
                        </td>
                        <td className="px-3 py-2 text-right tabular">{formatCurrency(row.portfolioValueAfter)}</td>
                        <td
                          className={cn(
                            "px-3 py-2 text-right tabular font-medium",
                            row.cumulativeReturnPct >= 0 ? "text-[var(--status-good)]" : "text-[var(--status-critical)]"
                          )}
                        >
                          {formatPct(row.cumulativeReturnPct, { signed: true })}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex justify-center">
                            {row.predictionCorrect ? (
                              <Check size={15} className="text-[var(--status-good)]" />
                            ) : (
                              <X size={15} className="text-[var(--status-critical)]" />
                            )}
                          </div>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="border-t border-base-700 bg-base-800/40">
                          <td colSpan={12} className="px-4 py-3">
                            <div className="mb-2 text-xs text-[var(--text-muted)]">
                              Raw k-NN call: <span className="font-medium text-[var(--text-secondary)]">{row.rawPrediction}</span> @{" "}
                              {(row.rawConfidence * 100).toFixed(0)}% confidence
                            </div>
                            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
                              <div className="flex items-center justify-between gap-2 rounded-lg border border-base-700 bg-base-850 px-3 py-2">
                                <div className="min-w-0">
                                  <div className="text-xs font-medium text-[var(--text-primary)]">Volatility regime override</div>
                                  <div className="truncate text-[11px] text-[var(--text-muted)]">{row.volatilityGuard.detail}</div>
                                </div>
                                <span
                                  className={cn(
                                    "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                                    row.volatilityGuard.pass ? "bg-long-muted text-long" : "bg-short-muted text-short"
                                  )}
                                >
                                  {row.volatilityGuard.pass ? <Check size={13} /> : <X size={13} />}
                                </span>
                              </div>
                              {(Object.keys(row.filters) as (keyof GmmaFilters)[]).map((k) => (
                                <div key={k} className="flex items-center justify-between gap-2 rounded-lg border border-base-700 bg-base-850 px-3 py-2">
                                  <div className="min-w-0">
                                    <div className="text-xs font-medium text-[var(--text-primary)]">{FILTER_LABELS[k]}</div>
                                    <div className="truncate text-[11px] text-[var(--text-muted)]">{row.filters[k].detail}</div>
                                  </div>
                                  <span
                                    className={cn(
                                      "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                                      row.filters[k].pass ? "bg-long-muted text-long" : "bg-short-muted text-short"
                                    )}
                                  >
                                    {row.filters[k].pass ? <Check size={13} /> : <X size={13} />}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
