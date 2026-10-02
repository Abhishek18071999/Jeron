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
