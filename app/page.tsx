"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, LineChart, NotebookPen } from "lucide-react";
import type { StrategyData } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import SignalCard from "@/components/SignalCard";
import TelemetryCard from "@/components/TelemetryCard";
import PortfolioStats from "@/components/PortfolioStats";
import AssetBreakdown from "@/components/AssetBreakdown";
import ProfitChart from "@/components/ProfitChart";
import LedgerTable from "@/components/LedgerTable";
import ValidationWindows from "@/components/ValidationWindows";

export default function Home() {
  const [data, setData] = useState<StrategyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Bundle lives in /public, so this is a same-origin static fetch -- no CORS,
      // no API round trip. The cache-busting query param forces a fresh read past
      // any browser/CDN cache when the user explicitly asks to re-query.
      const res = await fetch(`/strategy_data.json?t=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`Failed to load strategy_data.json (${res.status})`);
      const json: StrategyData = await res.json();
      setData(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error loading strategy data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-8 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <LineChart size={22} className="text-[var(--series-profit)]" />
            <h1 className="text-xl font-bold tracking-tight">GEAR / BBOZ Bi-Weekly ML Allocator</h1>
          </div>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Rolling k-NN (k=3) trend/vol/RSI classifier over GEAR.AX, BBOZ.AX &amp; cash · rebalanced
            Tuesdays &amp; Fridays · $500 seed, zero brokerage
            {data?.meta && (
              <>
                {" "}· trained on {Math.round(data.meta.trainWindowWeeks / 52)}y, evaluated out-of-sample over the
                trailing {data.meta.holdoutWindowWeeks}-week holdout
              </>
            )}
            .
          </p>
        </div>
        <div className="flex flex-col items-start gap-2 sm:items-end">
          {data?.generatedAt && (
            <div className="text-xs text-[var(--text-muted)]">Data generated {formatDateTime(data.generatedAt)}</div>
          )}
          <a
            href="/diary"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded-md border border-base-600 bg-base-800 px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] transition hover:bg-base-700"
          >
            <NotebookPen size={13} />
            Trading Diary
          </a>
        </div>
      </header>

      {error && (
        <div className="mb-6 flex items-center gap-2 rounded-lg border border-short-muted bg-short-muted/30 px-4 py-3 text-sm text-short">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {data?.status === "awaiting_first_run" && (
        <div className="mb-6 flex items-center gap-2 rounded-lg border border-base-600 bg-base-800 px-4 py-3 text-sm text-[var(--text-secondary)]">
          <AlertTriangle size={16} className="text-[var(--status-warning)]" />
          Awaiting the first scheduled engine run. This dashboard will populate automatically once{" "}
          <code className="rounded bg-base-700 px-1 py-0.5 text-xs">run_strategy.yml</code> completes on the next
          Tuesday/Friday cron, or you can trigger it manually from the Actions tab.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <SignalCard signal={data?.liveSignal ?? null} loading={loading} onRefresh={load} />
        </div>
        <div className="lg:col-span-2">
          <TelemetryCard />
        </div>
      </div>

      <div className="mt-4">{data && <PortfolioStats portfolio={data.portfolio} />}</div>

      <div className="mt-4">{data && <AssetBreakdown breakdown={data.portfolio.assetBreakdown} />}</div>

      <div className="mt-4 rounded-xl border border-base-700 bg-base-850 p-5">
        <h2 className="mb-4 text-sm font-medium text-[var(--text-secondary)]">
          Cumulative Profit — {data?.meta?.holdoutWindowWeeks ?? "—"} Week Holdout Walk-Forward
        </h2>
        <ProfitChart data={data?.chartSeries ?? []} />
      </div>

      <div className="mt-4">
        <ValidationWindows validation={data?.validation} holdoutWindowWeeks={data?.meta?.holdoutWindowWeeks} />
      </div>

      <div className="mt-4">
        <LedgerTable ledger={data?.ledger ?? []} holdoutWindowWeeks={data?.meta?.holdoutWindowWeeks} />
      </div>

      <footer className="mt-8 text-center text-xs text-[var(--text-muted)]">
        Zero-brokerage backtest for research purposes only. Not financial advice.
      </footer>
    </main>
  );
}
