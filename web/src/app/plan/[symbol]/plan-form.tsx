"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Help, buttonClass, inputClass, inr, pctText } from "@/components/ui";
import type { PlanCheck, PlanResult, PlanView } from "@/lib/api";

type Props = {
  symbol: string;
  signalId: string | null;
  initial: { entry: string; stop: string; tier: "swing" | "positional"; reason: string };
  stopHint: string;
  plan: PlanResult | null;
  checklist: PlanView["checklist"];
  action: (form: FormData) => Promise<void>;
};

const checkIcon: Record<PlanCheck["status"], { mark: string; tone: string; label: string }> = {
  pass: { mark: "✓", tone: "text-muted", label: "passed" },
  fail: { mark: "✕", tone: "text-bad", label: "failed" },
  warn: { mark: "!", tone: "text-warn", label: "warning" },
};

const ratio = (v: string | null | undefined) => (v === null || v === undefined ? "-" : `${Number(v).toFixed(2)}`);

function Figure({ label, value, sub, help, tone = "" }: { label: string; value: React.ReactNode; sub?: React.ReactNode; help?: string; tone?: string }) {
  return (
    <div className="min-w-0 rounded-lg bg-surface-2 px-3 py-2">
      <p className="text-xs text-muted">
        {label}
        {help && <Help text={help} />}
      </p>
      <p className={`mt-0.5 truncate text-lg font-semibold tracking-tight ${tone}`}>{value}</p>
      {sub && <p className="truncate text-xs text-muted">{sub}</p>}
    </div>
  );
}

// A before -> after bar against a limit (heat against the block level, a sector against
// its cap), with a mark at the warning level when there is one.
function LimitBar({
  label,
  before,
  after,
  limit,
  warn,
  help,
}: {
  label: string;
  before: number;
  after: number;
  limit: number;
  warn?: number;
  help: string;
}) {
  const scale = Math.max(limit * 1.25, after);
  const over = after > limit;
  const hot = over || (warn !== undefined && after >= warn);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-xs text-muted">
        <span className="min-w-0 truncate">
          {label}
          <Help text={help} />
        </span>
        <span className="shrink-0">
          {pctText(before, 1)} →{" "}
          <span className={`font-medium ${over ? "text-bad" : hot ? "text-warn" : "text-fg"}`}>{pctText(after, 1)}</span>{" "}
          / {pctText(limit, 0)}
        </span>
      </div>
      <div className="relative mt-1.5 h-2 overflow-hidden rounded-full bg-surface-2">
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${over ? "bg-bad/60" : hot ? "bg-warn/60" : "bg-accent/40"}`}
          style={{ width: `${Math.min(100, (after / scale) * 100)}%` }}
        />
        <div className="absolute inset-y-0 left-0 rounded-full bg-fg/60" style={{ width: `${Math.min(100, (before / scale) * 100)}%` }} />
        {warn !== undefined && (
          <div className="absolute inset-y-0 w-px bg-line-strong" style={{ left: `${(warn / scale) * 100}%` }} />
        )}
        <div className="absolute inset-y-0 w-0.5 bg-fg/50" style={{ left: `${(limit / scale) * 100}%` }} />
      </div>
    </div>
  );
}

export function PlanForm({ symbol, signalId, initial, stopHint, plan: first, checklist, action }: Props) {
  const [entry, setEntry] = useState(initial.entry);
  const [stop, setStop] = useState(initial.stop);
  const [tier, setTier] = useState(initial.tier);
  const [plan, setPlan] = useState<PlanResult | null>(first);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const firstRun = useRef(true);

  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
    if (!(Number(entry) > 0) || !(Number(stop) > 0)) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setBusy(true);
      try {
        const query = new URLSearchParams({ symbol, entry, stop, tier, ...(signalId ? { signal_id: signalId } : {}) });
        const res = await fetch(`/api/plan?${query}`, { signal: controller.signal });
        const body = await res.json();
        if (res.ok) {
          setPlan((body as PlanView).plan);
          setError(null);
        } else {
          setError(typeof body?.detail === "string" ? body.detail : "Could not size the plan");
        }
      } catch {
        // A newer keystroke aborted this request.
      } finally {
        setBusy(false);
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [symbol, signalId, entry, stop, tier]);

  const missing = !(Number(entry) > 0) || !(Number(stop) > 0);
  const problem = missing ? "Enter an entry and a stop price." : error;
  const unticked = checklist.filter((c) => !ticked.has(c.key));
  const blockers = useMemo(() => plan?.blockers ?? [], [plan]);
  const canSave = !!plan && plan.ok && unticked.length === 0 && !busy && !problem;
  const hard = plan?.checks.filter((c) => c.hard) ?? [];
  const soft = plan?.checks.filter((c) => !c.hard) ?? [];

  return (
    <form action={action} onSubmit={() => setSubmitting(true)} className="space-y-5">
      {signalId && <input type="hidden" name="signal_id" value={signalId} />}
      <fieldset className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
        <legend className="sr-only">Levels</legend>
        <label className="space-y-1 text-sm">
          <span className="text-muted">Entry ₹</span>
          <input
            name="entry"
            inputMode="decimal"
            required
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            className={`${inputClass} py-2 text-base`}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-muted">Stop ₹</span>
          <input
            name="stop"
            inputMode="decimal"
            required
            value={stop}
            onChange={(e) => setStop(e.target.value)}
            aria-describedby="stop-hint"
            className={`${inputClass} py-2 text-base`}
          />
        </label>
        <div className="space-y-1 text-sm">
          <span className="text-muted" id="tier-label">
            Tier
          </span>
          <div role="radiogroup" aria-labelledby="tier-label" className="flex rounded-lg border border-line-strong p-0.5">
            {(["swing", "positional"] as const).map((t) => (
              <label
                key={t}
                className={`flex-1 cursor-pointer rounded-md px-3 py-1.5 text-center text-sm font-medium capitalize ${
                  tier === t ? "bg-surface-2 text-fg" : "text-muted"
                }`}
              >
                <input
                  type="radio"
                  name="tier"
                  value={t}
                  checked={tier === t}
                  onChange={() => setTier(t)}
                  className="sr-only"
                />
                {t}
              </label>
            ))}
          </div>
        </div>
        {stopHint && (
          <p id="stop-hint" className="text-xs text-muted sm:col-span-3">
            Suggested stop: {stopHint}. Put it where the setup fails, not on a round number.
          </p>
        )}
      </fieldset>

      {problem && <p className="rounded-lg border border-bad/30 bg-bad-bg px-3 py-2 text-sm text-bad">{problem}</p>}

      {plan && !missing && (
        <div className={`space-y-5 transition-opacity ${busy ? "opacity-60" : ""}`} aria-live="polite" aria-busy={busy}>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Figure
              label="Shares"
              value={plan.shares.toLocaleString("en-IN")}
              sub={`set by ${plan.sized_by}`}
              tone="text-accent"
              help={`Engine sizing: ${plan.risk_pct}% of capital${plan.risk_multiplier !== 1 ? ` x${plan.risk_multiplier} (defend)` : ""} over the risk per share, capped at 20% of capital and 1% of the 20-day average volume.`}
            />
            <Figure label="Rupee risk" value={inr(plan.risk_amount, 0)} sub={`${inr(plan.risk_per_share)} a share`} />
            <Figure label="Position" value={inr(plan.position_value, 0)} sub={`${pctText(plan.position_pct, 1)} of capital`} />
            <Figure
              label="Stop distance"
              value={pctText(plan.stop_distance_pct, 1)}
              sub={plan.stop_atr ? `${Number(plan.stop_atr).toFixed(1)} x ATR` : "ATR unknown"}
            />
            <Figure label="Target 1 (+2R)" value={inr(plan.target1)} sub="book half here" />
            <Figure label="Target 2 (+3R)" value={inr(plan.target2)} sub="trail the rest" />
            <Figure
              label="Reward:risk T2"
              value={ratio(plan.reward_risk_t2)}
              sub={plan.round_trip_costs ? `after ~${inr(plan.round_trip_costs, 0)} costs` : "after costs"}
              help="Reward to target 2 over the risk, with estimated charges and slippage taken off the reward and added to the risk (the engine's rule)."
            />
            <Figure label="Reward:risk T1" value={ratio(plan.reward_risk_t1)} sub="after costs" />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <LimitBar
              label="Portfolio heat"
              before={Number(plan.heat_before_pct)}
              after={Number(plan.heat_after_pct)}
              limit={Number(plan.heat_block_pct)}
              warn={Number(plan.heat_warn_pct)}
              help={`Open risk of every position plus this one, as % of capital. Warning at ${plan.heat_warn_pct}%, no new entries above ${plan.heat_block_pct}%.`}
            />
            <LimitBar
              label="Sector exposure"
              before={Number(plan.sector_before_pct)}
              after={Number(plan.sector_after_pct)}
              limit={Number(plan.sector_cap_pct)}
              help={`What you hold in this stock's industry plus this buy, as % of capital. Cap ${plan.sector_cap_pct}%.`}
            />
          </div>

          <div>
            <h3 className="mb-1.5 text-sm font-semibold">Checks</h3>
            <ul className="divide-y divide-line rounded-lg border border-line">
              {[...hard, ...soft].map((c) => {
                const icon = checkIcon[c.status];
                return (
                  <li key={c.key} className="flex gap-2.5 px-3 py-2 text-sm">
                    <span aria-label={icon.label} className={`w-4 shrink-0 text-center font-bold ${icon.tone}`}>
                      {icon.mark}
                    </span>
                    <span className="min-w-0">
                      <span className={c.status === "fail" ? "font-medium text-bad" : ""}>{c.label}</span>
                      {!c.hard && <span className="ml-1.5 text-xs text-muted">(info)</span>}
                      <span className="block text-xs text-muted">{c.detail}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}

      <label className="block space-y-1 text-sm">
        <span className="text-muted">Reason for the trade</span>
        <textarea
          name="reason"
          rows={2}
          defaultValue={initial.reason}
          placeholder="The setup, and what would prove it wrong"
          className={inputClass}
        />
      </label>

      <fieldset>
        <legend className="mb-1.5 text-sm font-semibold">Before you buy</legend>
        <ul className="space-y-1">
          {checklist.map((c) => (
            <li key={c.key}>
              <label className="flex cursor-pointer items-start gap-2.5 rounded-lg px-1 py-1.5 text-sm hover:bg-surface-2">
                <input
                  type="checkbox"
                  name="checklist"
                  value={c.key}
                  checked={ticked.has(c.key)}
                  onChange={(e) => {
                    const next = new Set(ticked);
                    if (e.target.checked) next.add(c.key);
                    else next.delete(c.key);
                    setTicked(next);
                  }}
                  className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]"
                />
                {c.label}
              </label>
            </li>
          ))}
        </ul>
      </fieldset>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <button type="submit" disabled={!canSave || submitting} className={`${buttonClass} px-4 py-2 disabled:cursor-not-allowed`}>
          {submitting ? "Saving…" : "Save plan"}
        </button>
        {!canSave && (
          <div className="min-w-0 text-xs text-muted" role="status">
            {blockers.length > 0 ? (
              <>
                <span className="font-medium text-bad">Blocked:</span> {blockers.join(" · ")}
              </>
            ) : unticked.length > 0 ? (
              `Tick ${unticked.length === checklist.length ? "every item" : `the ${unticked.length} remaining item${unticked.length > 1 ? "s" : ""}`} above to save.`
            ) : busy ? (
              "Recalculating…"
            ) : null}
          </div>
        )}
        {canSave && <p className="text-xs text-muted">Saved plans are never changed; saving again makes a new one.</p>}
      </div>
    </form>
  );
}
