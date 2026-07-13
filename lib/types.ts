export type PriceSource =
  | "intraday_14:00"
  | "intraday_latest_partial"
  | "daily_close"
  | string;

export type Asset = "GEAR" | "BBOZ" | "CASH";
export type Direction = "UP" | "FLAT" | "DOWN";
export type PositionAction = "ENTER" | "HOLD" | "FLIP" | "EXIT" | "CASH";

export interface Streak {
  type: "W" | "L";
  length: number;
}

export interface FilterCheck {
  pass: boolean;
  detail: string;
}

export interface GmmaFilters {
  trendAlignment: FilterCheck;
  relativeStrength: FilterCheck;
  liquidity: FilterCheck;
  pullbackNotExtended: FilterCheck;
}

export interface LiveSignal {
  asOfSessionDate: string;
  asOfTimestamp: string;
  priceSource: PriceSource;
  rawPrediction: Asset;
  recommendedAsset: Asset;
  action: PositionAction;
  currentlyHolding: Asset;
  confidence: number;
  features: {
    shortGroupCompressionPct: number;
    longGroupSeparationPct: number;
    priceVsShortGroupPct: number;
  };
  filters: GmmaFilters;
  volatilityGuard: FilterCheck;
  lastPrices: {
    GEAR: number;
    BBOZ: number;
  };
  trainingSamples: number;
  currentStreak: Streak | null;
}

export interface AssetBreakdownEntry {
  trades: number;
  wins: number;
  losses: number;
  winRatePct: number;
  dollarPnl: number;
  contributionPct: number;
}

export interface AssetBreakdown {
  GEAR: AssetBreakdownEntry;
  BBOZ: AssetBreakdownEntry;
}

export interface PortfolioMetrics {
  initialCapital: number;
  currentValue: number;
  totalReturnPct: number;
  totalTrades: number;
  wins: number;
  losses: number;
  cashSessions: number;
  winRatePct: number;
  currentStreak: Streak | null;
  assetBreakdown: AssetBreakdown;
  buyHoldGearReturnPct: number;
  beatBuyHoldGear: boolean;
  buyHoldAxjoReturnPct: number;
  beatBuyHoldAxjo: boolean;
  sharpeRatio: number;
  maxDrawdownPct: number;
}

export interface LedgerRow {
  decisionDate: string;
  realizationDate: string;
  allocatedAsset: Asset;
  action: PositionAction;
  rawPrediction: Asset;
  rawConfidence: number;
  filters: GmmaFilters;
  volatilityGuard: FilterCheck;
  actualDirection: Direction;
  predictionCorrect: boolean;
  gearPrice: number;
  bbozPrice: number;
  intervalReturnPct: number;
  spreadCostPct: number;
  portfolioValueBefore: number;
  portfolioValueAfter: number;
  cumulativeReturnPct: number;
  priceSource: PriceSource;
}

export interface ChartPoint {
  date: string | null;
  portfolioValue: number;
  cumulativeProfit: number;
}

export interface ValidationWindow extends PortfolioMetrics {
  windowIndex: number;
  startDate: string;
  endDate: string;
}

export interface ValidationSummary {
  windowsEvaluated: number;
  meanWinRatePct?: number;
  stdDevWinRatePct?: number;
  meanTotalReturnPct?: number;
  stdDevTotalReturnPct?: number;
  meanBuyHoldGearReturnPct?: number;
  windowsBeatingBuyHoldGear?: number;
  meanBuyHoldAxjoReturnPct?: number;
  windowsBeatingBuyHoldAxjo?: number;
  meanSharpeRatio?: number;
  meanMaxDrawdownPct?: number;
  worstMaxDrawdownPct?: number;
}

export interface Validation {
  windows: ValidationWindow[];
  summary: ValidationSummary;
}

export interface StrategyMeta {
  strategy: string;
  tickers: { long: string; short: string; underlying: string };
  model: {
    type: string;
    k: number;
    distance: string;
    classes: string[];
    flatBandPct: number;
    signalSetup: string;
    features: string[];
    filterGate: string;
    filters: string[];
    volatilityGuard: string;
  };
  rebalanceSchedule: string;
  decisionCutoffLocal: string;
  trainWindowWeeks: number;
  holdoutWindowWeeks: number;
  backtestWindowWeeks: number;
  brokerageFees: number;
  timezone: string;
  knownSplits: Record<string, Record<string, number>>;
}

export interface StrategyData {
  generatedAt: string | null;
  status?: "awaiting_first_run";
  meta: StrategyMeta;
  liveSignal: LiveSignal | null;
  portfolio: PortfolioMetrics;
  ledger: LedgerRow[];
  chartSeries: ChartPoint[];
  validation: Validation;
}

export interface WorkflowStatus {
  status: string | null;
  conclusion: string | null;
  name: string | null;
  runStartedAt: string | null;
  updatedAt: string | null;
  htmlUrl: string | null;
  event: string | null;
  runNumber: number | null;
  error?: string;
}
