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

// --- Signals and paper trading (M4) ----------------------------------------------------

export type PaperAccountSummary = {
  as_of?: string;
  equity?: number;
  return_pct?: number;
  drawdown_pct?: number;
  max_drawdown_pct?: number;
  heat_pct?: number;
  open_positions?: number;
  pending_orders?: number;
  closed_trades?: TradeStats;
  skipped_today?: Record<string, number>;
  brake_events?: { date: string; event: string }[];
  notes?: string[];
};

export type PaperAccount = {
  id: number;
  strategy_key: string;
  strategy_version: string;
  strategy_name: string;
  tier: string;
  params_label: string;
  backtest_run_id: number;
  live_eligible: boolean;
  stage: "paper" | "research only";
  start_date: string;
  last_date: string | null;
  capital: string;
  status: string;
  rules: Record<string, unknown>;
  summary: PaperAccountSummary;
};

export type PaperTrade = {
  seq: number;
  signal_id: string | null;
  ticker: string;
  status: "open" | "closed";
  signal_date: string;
  entry_date: string;
  entry_price: string;
  initial_stop: string;
  target_t1: string;
  shares: number;
  current_stop: string | null;
  last_close: string | null;
  shares_held: number;
  exit_date: string | null;
  exit_price: string | null;
  exit_reason: string | null;
  charges: string;
  dividends: string;
  net_pnl: string;
  r_multiple: string;
  sessions: number;
  exits: { date: string; price: string; shares: number; reason: string }[];
};

export type PaperDay = {
  trade_date: string;
  equity: string;
  drawdown_pct: string;
  heat_pct: string;
  open_positions: number;
};

// The spec's section 4 schema, as the backend stores it (prices as strings).
export type SignalPayload = {
  signal_id: string;
  created_at: string;
  data_as_of: string;
  ticker: string;
  setup_name: string;
  strategy_version: string;
  tier: string;
  direction: "long";
  why: string[];
  entry_zone: { low: string; high: string; valid_until: string };
  stop: { price: string; type: string; reason: string };
  targets: { t1: string; t2: string; basis: string };
  risk_reward_t1: string;
  risk_reward_t2: string;
  expected_holding: { min_days: number; max_days: number };
  shares: number;
  capital_at_risk: string;
  exit_plan: string;
  time_stop_days: number;
  invalidation: string;
  event_risk: string;
  conviction: number;
  brains_breakdown: {
    technical: string;
    fundamental: string | null;
    news: string | null;
    combined: string;
  };
  backtest_stats: {
    trades: number;
    win_rate: string;
    avg_R: string;
    expectancy_R: string;
    profit_factor: string | null;
    max_drawdown_pct: string;
    period: string;
  };
  research_only: boolean;
  notes: string[];
};

export type SignalView = {
  signal_id: string;
  version: number;
  account_id: number;
  strategy_key: string;
  ticker: string;
  signal_date: string;
  research_only: boolean;
  late: boolean;
  created_at: string;
  payload: SignalPayload;
};

export type PaperAccountView = {
  account: PaperAccount;
  open_trades: PaperTrade[];
  closed_trades: PaperTrade[];
  days: PaperDay[];
  signals: SignalView[];
};

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

// --- Journal, dashboard, stock page and alerts (M5) --------------------------------

export type SignalBrief = {
  signal_id: string;
  ticker: string;
  signal_date: string;
  strategy_key: string;
  research_only: boolean;
  setup_name: string;
  conviction: number;
  entry_low: string;
  entry_high: string;
  valid_until: string;
  stop: string;
  t1: string;
  t2: string;
  shares: number;
  capital_at_risk: string;
};

export type JournalFill = {
  id: number;
  trade_date: string;
  side: "buy" | "sell";
  shares: number;
  price: string;
  charges: string;
  charges_estimated: boolean;
  source: "manual" | "tradebook";
};

export type TradebookImport = {
  added: number;
  already: number;
  to_signals: number;
  new_entries: number;
  skipped: Record<string, number>;
  problems: string[];
};

export type JournalPosition = {
  status: "no fills" | "open" | "closed";
  bought: number;
  sold: number;
  held: number;
  avg_entry: string | null;
  avg_exit: string | null;
  first_date: string | null;
  last_date: string | null;
  charges: string;
  realised_pnl: string;
  open_pnl: string | null;
  initial_risk: string | null;
  r_multiple: string | null;
};

export type JournalEntry = {
  id: number;
  ticker: string;
  strategy_key: string | null;
  decision: "taken" | "skipped" | "modified";
  reason: string;
  stop: string | null;
  own_stop: boolean;
  followed_plan: boolean | null;
  notes: string;
  created_at: string;
  updated_at: string;
  signal: SignalBrief | null;
  fills: JournalFill[];
  last_close: string | null;
  last_close_date: string | null;
  position: JournalPosition;
};

export type JournalStats = {
  strategy_key: string | null;
  signals: number;
  pending: number;
  taken: number;
  skipped: number;
  modified: number;
  open: number;
  closed: number;
  wins: number;
  win_rate: string | null;
  avg_r: string | null;
  profit_factor: string | null;
  net_pnl: string;
  avg_holding_days: string | null;
  followed: number;
  deviated: number;
  followed_avg_r: string | null;
  deviated_avg_r: string | null;
};

export type JournalView = {
  entries: JournalEntry[];
  pending: SignalBrief[];
  stats: JournalStats[];
};

export type SignalJournal = {
  signal: SignalBrief;
  payload: SignalPayload;
  entry: JournalEntry | null;
};

export type AlertRecord = {
  id: number;
  key: string;
  kind: "signal" | "digest" | "test";
  trade_date: string | null;
  signal_id: string | null;
  status: "sent" | "failed";
  channel: string | null;
  error: string | null;
  attempts: number;
  sent_at: string | null;
  created_at: string;
  text: string;
};

export type Dashboard = {
  as_of: string | null;
  quality: QualitySummary | null;
  scan: {
    trade_date: string;
    status: string;
    universe_size: number;
    reasons: string[];
    top: { symbol: string; score: string; close: string }[];
  } | null;
  regime: { regime: "bull" | "bear" | "sideways"; rule: string; risk_off: boolean } | null;
  signals: SignalBrief[];
  accounts: {
    id: number;
    strategy_key: string;
    stage: "paper" | "research only";
    equity: string;
    return_pct: string;
    open_positions: number;
    heat_pct: string;
    drawdown_pct: string;
  }[];
  paper_positions: {
    account_id: number;
    strategy_key: string;
    research_only: boolean;
    ticker: string;
    entry_date: string;
    entry_price: string;
    current_stop: string | null;
    last_close: string | null;
    shares_held: number;
    r_multiple: string;
    net_pnl: string;
  }[];
  journal_positions: JournalEntry[];
  pending: SignalBrief[];
  alerts: { telegram: boolean; email: boolean; research_signals: boolean };
  last_summary: AlertRecord | null;
};

export type Candle = {
  time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
  factor: string;
  ema50: number | null;
  ema200: number | null;
};

export type StockSignal = {
  signal: SignalBrief;
  chart: { entry_low: string; entry_high: string; stop: string; t1: string; t2: string };
  payload: SignalPayload;
};

export type StockView = {
  symbol: string;
  name: string | null;
  series: string;
  sector: string | null;
  industry: string | null;
  candles: Candle[];
  scores: { trade_date: string; score: string; rank: number }[];
  latest_scan: {
    trade_date: string;
    score: string;
    rank: number;
    in_nifty500: boolean;
    components: ScanComponent[];
    indicators: Record<string, number | null>;
  } | null;
  signals: StockSignal[];
  paper_trades: {
    account_id: number;
    strategy_key: string;
    status: "open" | "closed";
    entry_date: string;
    entry_price: string;
    exit_date: string | null;
    exit_price: string | null;
    exit_reason: string | null;
    r_multiple: string;
  }[];
  journal: JournalEntry[];
};

// Writes go through Next.js server actions, so only the server calls these.
export async function sendJson<T>(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${apiUrl()}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok) {
      const data = (await res.json().catch(() => null)) as { detail?: unknown } | null;
      const detail =
        typeof data?.detail === "string"
          ? data.detail
          : Array.isArray(data?.detail)
            ? data.detail.map((d: { msg?: string }) => d.msg ?? "").join("; ")
            : `HTTP ${res.status}`;
      return { ok: false, error: detail };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch {
    return { ok: false, error: "The backend is not reachable" };
  }
}

export type CompareRecord = {
  trades: number;
  win_rate: number | null;
  expectancy_r: number | null;
  profit_factor: number | null;
  avg_sessions: number | null;
  max_drawdown: number | null;
  drawdown_unit: "%" | "R";
  start: string | null;
  end: string | null;
};

export type CompareGate = { name: string; status: "passed" | "failed" | "not yet"; detail: string };

export type StrategyCompare = {
  account_id: number | null;
  strategy_key: string | null;
  strategy_version: string | null;
  params_label: string | null;
  live_eligible: boolean;
  account_status: string | null;
  backtest_run_id: number | null;
  backtest: CompareRecord | null;
  paper: CompareRecord | null;
  real: CompareRecord;
  paper_gate: CompareGate | null;
  real_gate: CompareGate | null;
  paper_range: [number, number] | null;
  real_range: [number, number] | null;
  stage: string;
  divergence: {
    pairs: number;
    slippage_r: number | null;
    late_days: number | null;
    exit_gap_r: number | null;
    skipped: number;
    skipped_r: number;
    skipped_winners: number;
    causes: string[];
  } | null;
};
