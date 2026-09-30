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
