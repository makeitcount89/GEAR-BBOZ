"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import type { DiaryEntry } from "@/lib/diary";

interface Props {
  onAdd: (entry: Omit<DiaryEntry, "id">) => void;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

const FIELD_CLS =
  "mt-1 w-full rounded-md border border-base-600 bg-base-800 px-2 py-1.5 text-sm text-[var(--text-primary)] focus:border-accent focus:outline-none";

export default function DiaryForm({ onAdd }: Props) {
  const [ticker, setTicker] = useState("GEAR");
  const [buyDate, setBuyDate] = useState(todayIso());
  const [buyPrice, setBuyPrice] = useState("");
  const [dollarAmount, setDollarAmount] = useState("");
  const [notes, setNotes] = useState("");

  const canSubmit = ticker.trim() !== "" && buyDate !== "" && Number(buyPrice) > 0 && Number(dollarAmount) > 0;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    onAdd({
      ticker: ticker.trim().toUpperCase(),
      buyDate,
      buyPrice: Number(buyPrice),
      dollarAmount: Number(dollarAmount),
      sellDate: null,
      sellPrice: null,
      notes: notes.trim(),
    });
    setBuyPrice("");
    setDollarAmount("");
    setNotes("");
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-base-700 bg-base-850 p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
        <Plus size={16} className="text-[var(--series-profit)]" />
        Add Trade
      </h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div>
          <label className="text-xs text-[var(--text-muted)]">Ticker</label>
          <input
            list="ticker-suggestions"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="GEAR"
            className={FIELD_CLS}
          />
          <datalist id="ticker-suggestions">
            <option value="GEAR" />
            <option value="BBOZ" />
          </datalist>
        </div>
        <div>
          <label className="text-xs text-[var(--text-muted)]">Buy Date</label>
          <input type="date" value={buyDate} onChange={(e) => setBuyDate(e.target.value)} className={FIELD_CLS} />
        </div>
        <div>
          <label className="text-xs text-[var(--text-muted)]">Buy Price ($)</label>
          <input
            type="number"
            step="0.001"
            min="0"
            value={buyPrice}
            onChange={(e) => setBuyPrice(e.target.value)}
            placeholder="0.000"
            className={`${FIELD_CLS} tabular`}
          />
        </div>
        <div>
          <label className="text-xs text-[var(--text-muted)]">$ Invested</label>
          <input
            type="number"
            step="0.01"
            min="0"
            value={dollarAmount}
            onChange={(e) => setDollarAmount(e.target.value)}
            placeholder="0.00"
            className={`${FIELD_CLS} tabular`}
          />
        </div>
        <div className="sm:col-span-2 lg:col-span-1">
          <label className="text-xs text-[var(--text-muted)]">Notes (optional)</label>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Why this trade"
            className={FIELD_CLS}
          />
        </div>
        <div className="flex items-end">
          <button
            type="submit"
            disabled={!canSubmit}
            className="mt-1 flex w-full items-center justify-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-base-950 transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Plus size={14} />
            Add
          </button>
        </div>
      </div>
    </form>
  );
}
