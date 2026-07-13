"use client";

import { ArrowDownRight, ArrowUpRight, Check, CircleDollarSign, RefreshCw, X, Zap } from "lucide-react";
import type { Asset, FilterCheck, LiveSignal, PositionAction } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

interface Props {
  signal: LiveSignal | null;
  loading: boolean;
  onRefresh: () => void;
}

const SOURCE_LABEL: Record<string, string> = {
  "intraday_14:00": "Intraday 14:00 ACST/ACDT bar",
  intraday_latest_partial: "Latest intraday bar (pre-14:00 partial)",
  daily_close: "Daily close (outside intraday retention)",
};

const ASSET_PRESENTATION: Record<Asset, { label: string; subtitle: string; badge: string; icon: React.ReactNode }> = {
  GEAR: {
    label: "GEAR",
    subtitle: "GEAR.AX (Long Geared)",
    badge: "bg-long-muted text-long",
    icon: <ArrowUpRight size={30} />,
  },
  BBOZ: {
    label: "BBOZ",
    subtitle: "BBOZ.AX (Short Geared)",
    badge: "bg-short-muted text-short",
    icon: <ArrowDownRight size={30} />,
  },
  CASH: {
    label: "CASH",
    subtitle: "Unreachable in the current design — kept for legacy ledger rows",
    badge: "bg-base-700 text-[var(--text-secondary)]",
    icon: <CircleDollarSign size={28} />,
  },
};

const ACTION_LABEL: Record<PositionAction, string> = {
  ENTER: "Entering",
  HOLD: "Holding",
  FLIP: "Flipping",
  EXIT: "Exiting to cash",
  CASH: "Staying in cash",
};

const ACTION_BADGE: Record<PositionAction, string> = {
  ENTER: "bg-base-700 text-[var(--text-primary)]",
  HOLD: "bg-accent-muted text-accent",
  FLIP: "bg-short-muted text-short",
  EXIT: "bg-base-700 text-[var(--text-muted)]",
  CASH: "bg-base-800 text-[var(--text-muted)]",
};

// GEAR is the default/home position with no filter gate of its own; BBOZ is entered
// either via all 4 confirmation filters unanimous, via the fast 20-day MA breakdown
// (price below its own 20-day MA -> BBOZ immediately), via the 20/50-day MA crossover
// (for sessions where price is back above the 20-day MA: 20-day MA still below the
// 50-day MA -> GEAR, reversal underway), or via the volatility regime override
// (elevated volatility + price above its 50-day MA -> BBOZ, below it -> GEAR). There
// is no CASH state produced by any path; CASH/EXIT are kept as action values only so
// pre-redesign ledger rows still render.

const FILTER_LABELS: Record<keyof LiveSignal["filters"], string> = {
  trendAlignment: "GMMA trend alignment",
  relativeStrength: "Relative strength",
  liquidity: "Above-average liquidity",
  pullbackNotExtended: "Pullback, not extended",
};

function FilterRow({ label, check }: { label: string; check: FilterCheck }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-base-700 bg-base-800/60 px-3 py-2">
      <div className="min-w-0">
        <div className="text-xs font-medium text-[var(--text-primary)]">{label}</div>
        <div className="truncate text-[11px] text-[var(--text-muted)]">{check.detail}</div>
      </div>
      <span
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
          check.pass ? "bg-long-muted text-long" : "bg-short-muted text-short"
        )}
      >
        {check.pass ? <Check size={13} /> : <X size={13} />}
      </span>
    </div>
  );
}

export default function SignalCard({ signal, loading, onRefresh }: Props) {
  const presentation = signal ? ASSET_PRESENTATION[signal.recommendedAsset] : null;

  return (
    <div className="rounded-xl border border-base-700 bg-base-850 p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
          <Zap size={16} className="text-[var(--series-profit)]" />
          Live Actionable Signal
        </h2>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-md border border-base-600 bg-base-800 px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] transition hover:bg-base-700 disabled:opacity-50"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          Query Live Signal Now
        </button>
      </div>

      {!signal || !presentation ? (
        <div className="mt-6 flex flex-col items-center justify-center gap-2 py-8 text-center">
          <p className="text-sm text-[var(--text-secondary)]">
            No live signal yet. The engine publishes one after its first scheduled Tuesday/Friday run.
          </p>
        </div>
      ) : (
        <>
          <div className="mt-5 flex items-center gap-4">
            <div className={cn("flex h-16 w-16 shrink-0 items-center justify-center rounded-full text-2xl font-bold", presentation.badge)}>
              {presentation.icon}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <div className="text-3xl font-bold tracking-tight">
                  {presentation.label}
                  <span className="ml-2 text-base font-normal text-[var(--text-muted)]">{presentation.subtitle}</span>
                </div>
                <span className={cn("rounded-md px-2 py-0.5 text-xs font-medium", ACTION_BADGE[signal.action])}>
                  {ACTION_LABEL[signal.action]}
                </span>
              </div>
              <div className="mt-1 text-sm text-[var(--text-secondary)]">
                GMMA k-NN confidence: <span className="font-semibold text-[var(--text-primary)]">{(signal.confidence * 100).toFixed(0)}%</span>
              </div>
              {!signal.volatilityGuard.pass && signal.recommendedAsset === "BBOZ" && (
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  Override active: either price has closed below its own 20-day MA (a fast breakdown trigger), or
                  realized volatility is elevated with price above its 50-day MA (a topping pattern) — see the
                  detail below for which. Switching to BBOZ regardless of the BBOZ gate below.
                </div>
              )}
              {!signal.volatilityGuard.pass && signal.recommendedAsset === "GEAR" && (
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  Override active: either price is back above its 20-day MA but the 20-day MA is still below the
                  50-day MA (a reversal already underway even though the medium-term trend hasn&apos;t caught up), or
                  realized volatility is elevated with price below its 50-day MA (an oversold bounce) — see the
                  detail below for which. Staying in GEAR regardless of the BBOZ gate below.
                </div>
              )}
              {signal.volatilityGuard.pass && signal.action === "HOLD" && signal.recommendedAsset === "BBOZ" && (
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  BBOZ still clears all 4 confirmation filters below, so continuing to hold it.
                </div>
              )}
              {signal.volatilityGuard.pass && signal.action === "HOLD" && signal.recommendedAsset === "GEAR" && (
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  GEAR is the default position — no confirmation filters required to hold it, and BBOZ doesn&apos;t clear all 4 filters below.
                </div>
              )}
              {signal.volatilityGuard.pass && signal.action === "FLIP" && signal.recommendedAsset === "BBOZ" && (
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  Raw GMMA call agrees with BBOZ and all 4 confirmation filters below pass unanimously, so switching out of GEAR into BBOZ.
                </div>
              )}
              {signal.volatilityGuard.pass && signal.action === "FLIP" && signal.recommendedAsset === "GEAR" && (
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  BBOZ no longer clears all 4 confirmation filters below, so reverting to GEAR, the default position.
                </div>
              )}
            </div>
          </div>

          <div className="mt-5 border-t border-base-700 pt-4">
            <div className="mb-2 text-xs text-[var(--text-muted)]">
              Fast breakdown, 20/50-day MA crossover, and volatility regime override — checked in this order,
              regardless of the BBOZ gate below: price below 20-day MA → BBOZ (fast breakdown); otherwise, if
              20-day MA is still below 50-day MA → GEAR (reversal underway); otherwise, when volatility is
              elevated: above 50-day MA → BBOZ (topping); below 50-day MA → GEAR (oversold bounce)
            </div>
            <FilterRow
              label="Price vs. 20-day MA, 20-day MA vs. 50-day MA, and realized volatility vs. its own baseline"
              check={signal.volatilityGuard}
            />
          </div>

          <div className="mt-5 border-t border-base-700 pt-4">
            <div className="mb-2 text-xs text-[var(--text-muted)]">
              BBOZ confirmation filters — all 4 required to enter BBOZ from GEAR; any single failure while holding BBOZ reverts to GEAR
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {(Object.keys(signal.filters) as (keyof LiveSignal["filters"])[]).map((key) => (
                <FilterRow key={key} label={FILTER_LABELS[key]} check={signal.filters[key]} />
              ))}
            </div>
          </div>

          <dl className="mt-4 grid grid-cols-3 gap-4 border-t border-base-700 pt-4 text-sm">
            <div>
              <dt className="text-xs text-[var(--text-muted)]">Short group compression</dt>
              <dd className="tabular font-medium">{signal.features.shortGroupCompressionPct.toFixed(2)}%</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-muted)]">Long group separation</dt>
              <dd className="tabular font-medium">{signal.features.longGroupSeparationPct.toFixed(2)}%</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-muted)]">Price vs short group</dt>
              <dd className="tabular font-medium">{signal.features.priceVsShortGroupPct.toFixed(2)}%</dd>
            </div>
          </dl>

          <dl className="mt-4 grid grid-cols-2 gap-4 border-t border-base-700 pt-4 text-sm sm:w-1/2">
            <div>
              <dt className="text-xs text-[var(--text-muted)]">GEAR.AX price</dt>
              <dd className="tabular font-medium">${signal.lastPrices.GEAR.toFixed(3)}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-muted)]">BBOZ.AX price</dt>
              <dd className="tabular font-medium">${signal.lastPrices.BBOZ.toFixed(3)}</dd>
            </div>
          </dl>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--text-muted)]">
            <span>As of {formatDateTime(signal.asOfTimestamp)}</span>
            <span>{SOURCE_LABEL[signal.priceSource] ?? signal.priceSource}</span>
            <span>{signal.trainingSamples} training samples</span>
          </div>
        </>
      )}
    </div>
  );
}
