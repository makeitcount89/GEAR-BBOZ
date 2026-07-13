export interface DiaryEntry {
  id: string;
  ticker: string;
  buyDate: string; // yyyy-mm-dd
  buyPrice: number;
  dollarAmount: number;
  sellDate: string | null;
  sellPrice: number | null;
  notes: string;
}

export interface DiaryState {
  startingCapital: number;
  entries: DiaryEntry[];
}

export const DEFAULT_STARTING_CAPITAL = 500;

const STORAGE_KEY = "gear-bboz-trading-diary-v1";

// Manual trading diary is entirely client-side (localStorage) -- there's no backend
// to persist to, and these are the user's own real trades, not engine-generated data.
export function loadDiaryState(): DiaryState {
  if (typeof window === "undefined") return { startingCapital: DEFAULT_STARTING_CAPITAL, entries: [] };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { startingCapital: DEFAULT_STARTING_CAPITAL, entries: [] };
    const parsed = JSON.parse(raw) as Partial<DiaryState>;
    return {
      startingCapital: typeof parsed.startingCapital === "number" ? parsed.startingCapital : DEFAULT_STARTING_CAPITAL,
      entries: Array.isArray(parsed.entries) ? parsed.entries : [],
    };
  } catch {
    return { startingCapital: DEFAULT_STARTING_CAPITAL, entries: [] };
  }
}

export function saveDiaryState(state: DiaryState): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function shares(entry: DiaryEntry): number {
  return entry.buyPrice > 0 ? entry.dollarAmount / entry.buyPrice : 0;
}

export function isClosed(entry: DiaryEntry): boolean {
  return entry.sellDate !== null && entry.sellDate !== "" && entry.sellPrice !== null;
}

export function realizedProfit(entry: DiaryEntry): number | null {
  if (!isClosed(entry) || entry.sellPrice === null) return null;
  return shares(entry) * entry.sellPrice - entry.dollarAmount;
}

export function realizedReturnPct(entry: DiaryEntry): number | null {
  const profit = realizedProfit(entry);
  if (profit === null || entry.dollarAmount === 0) return null;
  return (profit / entry.dollarAmount) * 100;
}

export function unrealizedProfit(entry: DiaryEntry, livePrice: number | null): number | null {
  if (isClosed(entry) || livePrice === null) return null;
  return shares(entry) * livePrice - entry.dollarAmount;
}

export function unrealizedReturnPct(entry: DiaryEntry, livePrice: number | null): number | null {
  const profit = unrealizedProfit(entry, livePrice);
  if (profit === null || entry.dollarAmount === 0) return null;
  return (profit / entry.dollarAmount) * 100;
}

export interface DiarySummary {
  closedTrades: number;
  openTrades: number;
  wins: number;
  losses: number;
  winRatePct: number;
  realizedProfitTotal: number;
  unrealizedProfitTotal: number;
  currentValue: number;
  cumulativeReturnPct: number;
  currentStreak: { type: "W" | "L"; length: number } | null;
}

export function summarizeDiary(state: DiaryState, livePrices: Record<string, number>): DiarySummary {
  const closed = state.entries.filter(isClosed);
  const open = state.entries.filter((e) => !isClosed(e));

  const realizedProfitTotal = closed.reduce((sum, e) => sum + (realizedProfit(e) ?? 0), 0);
  const unrealizedProfitTotal = open.reduce(
    (sum, e) => sum + (unrealizedProfit(e, livePrices[e.ticker.toUpperCase()] ?? null) ?? 0),
    0
  );

  const wins = closed.filter((e) => (realizedProfit(e) ?? 0) > 0).length;
  const losses = closed.length - wins;

  const currentValue = state.startingCapital + realizedProfitTotal + unrealizedProfitTotal;
  const cumulativeReturnPct =
    state.startingCapital > 0 ? ((realizedProfitTotal + unrealizedProfitTotal) / state.startingCapital) * 100 : 0;

  // Streak over closed trades only, most recently sold first.
  const closedSorted = [...closed].sort((a, b) => (b.sellDate ?? "").localeCompare(a.sellDate ?? ""));
  let streakType: "W" | "L" | null = null;
  let streakLen = 0;
  for (const e of closedSorted) {
    const profit = realizedProfit(e) ?? 0;
    const type: "W" | "L" = profit > 0 ? "W" : "L";
    if (streakType === null) {
      streakType = type;
      streakLen = 1;
    } else if (type === streakType) {
      streakLen += 1;
    } else {
      break;
    }
  }

  return {
    closedTrades: closed.length,
    openTrades: open.length,
    wins,
    losses,
    winRatePct: closed.length ? (wins / closed.length) * 100 : 0,
    realizedProfitTotal,
    unrealizedProfitTotal,
    currentValue,
    cumulativeReturnPct,
    currentStreak: streakType ? { type: streakType, length: streakLen } : null,
  };
}
