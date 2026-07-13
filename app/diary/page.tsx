"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, NotebookPen } from "lucide-react";
import {
  DEFAULT_STARTING_CAPITAL,
  type DiaryEntry,
  type DiaryState,
  loadDiaryState,
  saveDiaryState,
  summarizeDiary,
} from "@/lib/diary";
import type { StrategyData } from "@/lib/types";
import DiaryStats from "@/components/DiaryStats";
import DiaryForm from "@/components/DiaryForm";
import DiaryTable from "@/components/DiaryTable";

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function DiaryPage() {
  const [state, setState] = useState<DiaryState | null>(null);
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});

  // Diary state lives entirely in the browser (localStorage) -- these are the
  // user's own real trades, not engine-generated data, so there's nothing to fetch
  // from the server for the diary itself. Only wait for the client mount to read it,
  // so this never mismatches between server and client render.
  useEffect(() => {
    setState(loadDiaryState());
  }, []);

  useEffect(() => {
    if (state) saveDiaryState(state);
  }, [state]);

  // Live GEAR/BBOZ prices from the same strategy_data.json the ML dashboard already
  // publishes, purely to show unrealized P&L on open GEAR/BBOZ positions -- optional,
  // fails silently if unavailable.
  useEffect(() => {
    fetch(`/strategy_data.json?t=${Date.now()}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((json: StrategyData | null) => {
        if (json?.liveSignal?.lastPrices) {
          setLivePrices({
            GEAR: json.liveSignal.lastPrices.GEAR,
            BBOZ: json.liveSignal.lastPrices.BBOZ,
          });
        }
      })
      .catch(() => {});
  }, []);

  const addEntry = useCallback((entry: Omit<DiaryEntry, "id">) => {
    setState((prev) => {
      const base = prev ?? { startingCapital: DEFAULT_STARTING_CAPITAL, entries: [] };
      return { ...base, entries: [...base.entries, { ...entry, id: newId() }] };
    });
  }, []);

  const updateEntry = useCallback((id: string, patch: Partial<DiaryEntry>) => {
    setState((prev) => {
      if (!prev) return prev;
      return { ...prev, entries: prev.entries.map((e) => (e.id === id ? { ...e, ...patch } : e)) };
    });
  }, []);

  const deleteEntry = useCallback((id: string) => {
    setState((prev) => (prev ? { ...prev, entries: prev.entries.filter((e) => e.id !== id) } : prev));
  }, []);

  const setStartingCapital = useCallback((value: number) => {
    setState((prev) => (prev ? { ...prev, startingCapital: value } : prev));
  }, []);

  if (!state) {
    return null;
  }

  const summary = summarizeDiary(state, livePrices);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-8 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <NotebookPen size={22} className="text-[var(--series-profit)]" />
            <h1 className="text-xl font-bold tracking-tight">Trading Diary</h1>
          </div>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Your own real trades — enter what you bought, at what price, and how much you put in; enter a sell
            price whenever you close it out and P&amp;L, return %, and cumulative totals compute automatically.
            Stored only in this browser.
          </p>
        </div>
        <Link
          href="/"
          className="flex items-center gap-1.5 rounded-md border border-base-600 bg-base-800 px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] transition hover:bg-base-700"
        >
          <ArrowLeft size={13} />
          Back to ML Dashboard
        </Link>
      </header>

      <div className="mb-4 flex items-center gap-3 rounded-xl border border-base-700 bg-base-850 p-4">
        <label className="text-xs text-[var(--text-muted)]">Starting Capital ($)</label>
        <input
          type="number"
          step="0.01"
          min="0"
          value={state.startingCapital}
          onChange={(e) => setStartingCapital(Number(e.target.value))}
          className="w-32 rounded-md border border-base-600 bg-base-800 px-2 py-1.5 text-sm tabular text-[var(--text-primary)] focus:border-accent focus:outline-none"
        />
      </div>

      <DiaryStats summary={summary} />

      <div className="mt-4">
        <DiaryForm onAdd={addEntry} />
      </div>

      <div className="mt-4">
        <DiaryTable entries={state.entries} livePrices={livePrices} onUpdate={updateEntry} onDelete={deleteEntry} />
      </div>

      <footer className="mt-8 text-center text-xs text-[var(--text-muted)]">
        Your own trades, tracked for your own reference only. Not financial advice.
      </footer>
    </main>
  );
}
