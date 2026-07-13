"use client";

import { Trash2 } from "lucide-react";
import {
  type DiaryEntry,
  isClosed,
  realizedProfit,
  realizedReturnPct,
  shares,
  unrealizedProfit,
  unrealizedReturnPct,
} from "@/lib/diary";
import { cn, formatCurrency, formatPct } from "@/lib/utils";

interface Props {
  entries: DiaryEntry[];
  livePrices: Record<string, number>;
  onUpdate: (id: string, patch: Partial<DiaryEntry>) => void;
  onDelete: (id: string) => void;
}

const INPUT_CLS =
  "w-full rounded-md border border-base-600 bg-base-800 px-2 py-1 text-xs tabular text-[var(--text-primary)] focus:border-accent focus:outline-none";

export default function DiaryTable({ entries, livePrices, onUpdate, onDelete }: Props) {
  const sorted = [...entries].sort((a, b) => b.buyDate.localeCompare(a.buyDate));

  return (
    <div className="rounded-xl border border-base-700 bg-base-850 p-5">
      <h2 className="mb-4 text-sm font-medium text-[var(--text-secondary)]">
        Trades
        <span className="ml-2 rounded-full bg-base-800 px-2 py-0.5 text-xs text-[var(--text-muted)]">
          {entries.length} {entries.length === 1 ? "trade" : "trades"}
        </span>
      </h2>
      {entries.length === 0 ? (
        <p className="py-8 text-center text-sm text-[var(--text-secondary)]">
          No trades yet — add your first one above.
        </p>
      ) : (
        <div className="overflow-auto rounded-lg border border-base-700">
          <table className="w-full min-w-[1120px] border-collapse text-sm">
            <thead className="bg-base-800 text-xs text-[var(--text-muted)]">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Ticker</th>
                <th className="px-3 py-2 text-left font-medium">Buy Date</th>
                <th className="px-3 py-2 text-right font-medium">Buy Price</th>
                <th className="px-3 py-2 text-right font-medium">$ Invested</th>
                <th className="px-3 py-2 text-right font-medium">Shares</th>
                <th className="px-3 py-2 text-left font-medium">Sell Date</th>
                <th className="px-3 py-2 text-right font-medium">Sell Price</th>
                <th className="px-3 py-2 text-right font-medium">P&amp;L</th>
                <th className="px-3 py-2 text-right font-medium">Return</th>
                <th className="px-3 py-2 text-center font-medium">Status</th>
                <th className="px-3 py-2 text-left font-medium">Notes</th>
                <th className="w-8 px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((entry) => {
                const closed = isClosed(entry);
                const sh = shares(entry);
                const livePrice = livePrices[entry.ticker.toUpperCase()] ?? null;
                const profit = closed ? realizedProfit(entry) : unrealizedProfit(entry, livePrice);
                const returnPct = closed ? realizedReturnPct(entry) : unrealizedReturnPct(entry, livePrice);
                const positive = (profit ?? 0) >= 0;
                return (
                  <tr key={entry.id} className="border-t border-base-700">
                    <td className="px-3 py-2">
                      <input
                        value={entry.ticker}
                        onChange={(e) => onUpdate(entry.id, { ticker: e.target.value.toUpperCase() })}
                        className={cn(INPUT_CLS, "w-20 font-semibold")}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="date"
                        value={entry.buyDate}
                        onChange={(e) => onUpdate(entry.id, { buyDate: e.target.value })}
                        className={cn(INPUT_CLS, "w-36")}
                      />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="number"
                        step="0.001"
                        min="0"
                        value={entry.buyPrice}
                        onChange={(e) => onUpdate(entry.id, { buyPrice: Number(e.target.value) })}
                        className={cn(INPUT_CLS, "w-24 text-right")}
                      />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={entry.dollarAmount}
                        onChange={(e) => onUpdate(entry.id, { dollarAmount: Number(e.target.value) })}
                        className={cn(INPUT_CLS, "w-24 text-right")}
                      />
                    </td>
                    <td className="px-3 py-2 text-right tabular text-[var(--text-secondary)]">{sh.toFixed(4)}</td>
                    <td className="px-3 py-2">
                      <input
                        type="date"
                        value={entry.sellDate ?? ""}
                        onChange={(e) => onUpdate(entry.id, { sellDate: e.target.value || null })}
                        className={cn(INPUT_CLS, "w-36")}
                      />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="number"
                        step="0.001"
                        min="0"
                        value={entry.sellPrice ?? ""}
                        onChange={(e) =>
                          onUpdate(entry.id, { sellPrice: e.target.value === "" ? null : Number(e.target.value) })
                        }
                        placeholder="—"
                        className={cn(INPUT_CLS, "w-24 text-right")}
                      />
                    </td>
                    <td
                      className={cn(
                        "px-3 py-2 text-right tabular font-medium",
                        profit === null
                          ? "text-[var(--text-muted)]"
                          : positive
                            ? "text-[var(--status-good)]"
                            : "text-[var(--status-critical)]"
                      )}
                    >
                      {profit === null ? "—" : formatCurrency(profit)}
                    </td>
                    <td
                      className={cn(
                        "px-3 py-2 text-right tabular font-medium",
                        returnPct === null
                          ? "text-[var(--text-muted)]"
                          : positive
                            ? "text-[var(--status-good)]"
                            : "text-[var(--status-critical)]"
                      )}
                    >
                      {returnPct === null ? "—" : formatPct(returnPct, { signed: true })}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <span
                        className={cn(
                          "rounded-md px-2 py-0.5 text-xs font-medium",
                          closed ? "bg-base-700 text-[var(--text-muted)]" : "bg-accent-muted text-accent"
                        )}
                      >
                        {closed ? "Closed" : "Open"}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <input
                        value={entry.notes}
                        onChange={(e) => onUpdate(entry.id, { notes: e.target.value })}
                        placeholder="—"
                        className={cn(INPUT_CLS, "w-40")}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <button
                        onClick={() => onDelete(entry.id)}
                        className="text-[var(--text-muted)] transition hover:text-short"
                        title="Delete trade"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
