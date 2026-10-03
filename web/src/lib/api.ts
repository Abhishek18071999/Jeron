// Server-side calls to the Jeron backend. JERON_API_URL is read at request time,
// so the same build works locally and inside Docker Compose.
export const apiUrl = () => process.env.JERON_API_URL ?? "http://localhost:8000";

export type Health = { status: "ok" | "degraded"; database: "ok" | "unreachable" };

export async function fetchHealth(): Promise<Health | null> {
  try {
    const res = await fetch(`${apiUrl()}/health`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as Health;
  } catch {
    return null;
  }
}

// --- Market data (M1) -------------------------------------------------------------

export type QualityStatus = "pass" | "warn" | "fail";

export type QualitySummary = {
  trade_date: string;
  status: QualityStatus;
  reasons: string[];
};

export type DataStatus = {
  coverage: { source: string; first_date: string | null; last_date: string | null; days: number }[];
  instruments: number;
  corporate_actions: number;
  latest_quality: QualitySummary | null;
  scan_allowed: boolean;
};

export type QualityCheck = {
  name: string;
  status: QualityStatus;
  message: string;
  items: Record<string, string>[];
  item_count: number;
};

export type QualityReport = QualitySummary & { checks: QualityCheck[] };

export type Prices = { open: string; high: string; low: string; close: string; volume: number };

export type SpotRow = {
  trade_date: string;
  series: string;
  raw: Prices;
  prev_close: string | null;
  second_source_close: string | null;
  diff_pct: string | null;
  close_mismatch: boolean;
  factor: string;
  adjusted: Prices;
  ema20: number | null;
  ema50: number | null;
  ema200: number | null;
  rsi14: number | null;
  atr14: number | null;
  macd: number | null;
  macd_signal: number | null;
  adx14: number | null;
};

export type AdjustmentLogEntry = {
  ex_date: string;
  action_type: string;
  description: string;
  source: string;
  factor: string | null;
  applied: boolean;
  price_confirms: boolean | null;
  confirmed_by_second_source: boolean | null;
};

export type SpotCheck = {
  symbol: string;
  requested_date: string;
  include_dividends: boolean;
  rows: SpotRow[];
  adjustments: AdjustmentLogEntry[];
  notes: string[];
};

// --- Scanner (M2) -------------------------------------------------------------------

export type ScanRunSummary = {
  id: number;
  trade_date: string;
  score_version: string;
  status: "ok" | "blocked";
  universe_size: number;
  duration_seconds: string | null;
  reasons: string[];
  created_at: string;
};

export type ScanComponent = {
  key: string;
  label: string;
  value: number | null;
  points: number;
  max_points: number;
};

export type ScanIndicators = {
  sessions: number;
  close: number;
  rsi14: number | null;
  adx14: number | null;
  atr_pct: number | null;
  volume_ratio: number | null;
  below_52w_high_pct: number;
  return_3m: number | null;
  rs_3m: number | null;
  rs_6m: number | null;
  support: number | null;
  resistance: number | null;
  [key: string]: number | null;
};

export type ScanResult = {
  rank: number;
  symbol: string;
  score: string;
  close: string;
  in_nifty500: boolean;
  sector: string | null;
  components: ScanComponent[];
  indicators: ScanIndicators;
};

export type ScanExclusion = { rule: string; label: string; count: number; symbols: string[] };

export type ScanView = {
  run: ScanRunSummary;
  details: {
    candidates?: number;
    exclusions?: ScanExclusion[];
    notes?: string[];
    security_list_date?: string | null;
    asm_list_date?: string | null;
    reasons?: string[];
  };
  total_results: number;
  results: ScanResult[];
};

// --- Backtests (M3) -----------------------------------------------------------------

export type TradeStats = {
  trades: number;
  wins: number;
  win_rate: number;
  avg_r: number;
  expectancy_r: number;
  profit_factor: number | string;
  net_pnl: number;
  avg_win_r: number;
  avg_loss_r: number;
  avg_sessions: number;
};

export type CurveStats = {
  start_value: number;
  end_value: number;
  total_return: number;
  cagr: number;
  max_drawdown_pct: number;
  sharpe: number;
  volatility: number;
  sessions: number;
};

export type Gate = { key: string; label: string; value: string; passed: boolean };

export type BacktestRunSummary = {
  id: number;
  strategy_key: string;
  strategy_version: string;
  strategy_name: string;
  tier: string;
  data_start: string;
  data_end: string;
  oos_start: string;
  holdout_start: string;
  live_eligible: boolean;
  fingerprint: string;
  created_at: string;
  trades: TradeStats;
  curve: CurveStats;
  gates: Gate[];
};

export type TaxView = {
  pre_tax_pnl: number;
  interest?: number; // engine-v2 onwards: idle cash at a liquid-fund rate
  estimated_tax: number;
  post_tax_pnl: number;
  years: { fy: string; stcg: number; ltcg: number; dividends: number; interest?: number; tax: number; loss_carried: number }[];
};

export type BacktestSummary = {
  periods: { data: string[]; first_tradable: string; out_of_sample: string[]; holdout: string[] };
  out_of_sample: {
    trades: TradeStats;
    curve: CurveStats;
    benchmark: CurveStats;
    by_year: Record<string, TradeStats>;
    by_regime: Record<string, TradeStats>;
    yearly_returns: Record<string, number>;
    benchmark_yearly_returns: Record<string, number>;
    deflated_sharpe: number;
    variants_tried: number;
    tax: TaxView;
  };
  holdout: { trades: TradeStats; curve: CurveStats; benchmark: CurveStats };
  gates: Gate[];
  schedule: { from: string; variant: string; params: Record<string, number> }[];
  skipped_entries: Record<string, number>;
  exit_reasons: Record<string, number>;
  brake_events: { date: string; event: string }[];
  rules: string[];
  notes: string[];
  live_eligible: boolean;
};

export type EquityPoint = { date: string; equity: number; drawdown_pct: number; benchmark: number | null };

export type BacktestVariant = {
  window: string;
  label: string;
  params: Record<string, number>;
  train_start: string;
  train_end: string;
  trades: number;
  expectancy_r: string;
  sharpe: string;
  chosen: boolean;
};

export type BacktestView = {
  run: BacktestRunSummary;
  summary: BacktestSummary;
  equity: EquityPoint[];
  variants: BacktestVariant[];
  runs_of_strategy: number;
};

export type BacktestTrade = {
  seq: number;
  segment: "oos" | "holdout";
  symbol: string;
  variant: string;
  signal_date: string;
  entry_date: string;
  exit_date: string;
  entry_price: string;
  stop_price: string;
  target_price: string;
  exit_price: string;
  shares: number;
  exit_reason: string;
  gross_pnl: string;
  charges: string;
  dividends: string;
  net_pnl: string;
  r_multiple: string;
  regime: string;
  score: string;
  sessions: number;
  open_at_end: boolean;
};

export type SamplePick = { symbol: string; trade_date: string; reason: string };

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string };

export async function getJson<T>(path: string): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${apiUrl()}${path}`, { cache: "no-store" });
    if (!res.ok) {
      const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
      const detail = typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`;
      return { ok: false, error: detail };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch {
    return { ok: false, error: "The backend is not reachable" };
  }
}
