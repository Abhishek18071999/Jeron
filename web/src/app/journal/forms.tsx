import type { JournalEntry, SavedPlan } from "@/lib/api";
import { Card, LinkButton, buttonClass, inputClass, inr, shortDate } from "@/components/ui";

// The trade plan a journal entry was made from (or the latest plan for its signal).
export function PlanSummary({ plan, title = "Trade plan" }: { plan: SavedPlan; title?: string }) {
  return (
    <Card
      title={`${title} #${plan.id}`}
      subtitle={`Saved ${shortDate(plan.created_at.slice(0, 10))} · ${plan.tier} · market ${plan.mood ?? "unknown"}`}
      action={
        <LinkButton href={`/plan/${plan.ticker}${plan.signal_id ? `?signal=${plan.signal_id}` : ""}`} variant="ghost">
          Plan again
        </LinkButton>
      }
    >
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-muted">Buy</dt>
          <dd>
            {plan.shares.toLocaleString("en-IN")} at {inr(plan.entry)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Stop</dt>
          <dd>
            {inr(plan.stop)} <span className="text-xs text-muted">({Number(plan.stop_distance_pct).toFixed(1)}%)</span>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Targets (+2R / +3R)</dt>
          <dd>
            {inr(plan.target1)} / {inr(plan.target2)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Risk</dt>
          <dd>
            {inr(plan.risk_amount, 0)} <span className="text-xs text-muted">R:R {Number(plan.reward_risk_t2).toFixed(2)}</span>
          </dd>
        </div>
      </dl>
      {plan.reason && <p className="mt-2 text-sm">{plan.reason}</p>}
    </Card>
  );
}

export function PlanForm({
  action,
  entry,
  signalStop,
  plan,
}: {
  action: (form: FormData) => Promise<void>;
  entry?: JournalEntry | null;
  signalStop?: string | null;
  // A saved trade plan: the form starts from its stop and reason and links to it.
  plan?: SavedPlan | null;
}) {
  const followed = entry?.followed_plan === true ? "yes" : entry?.followed_plan === false ? "no" : "";
  const planStop = plan && (!signalStop || Number(plan.stop) !== Number(signalStop)) ? String(Number(plan.stop)) : "";
  return (
    <form action={action} className="grid gap-3 text-sm sm:grid-cols-2">
      {plan && <input type="hidden" name="plan_id" value={plan.id} />}
      <label className="space-y-1">
        <span className="text-muted">What I did</span>
        <select name="decision" defaultValue={entry?.decision ?? "taken"} className={inputClass}>
          <option value="taken">Taken as planned</option>
          <option value="modified">Taken, modified</option>
          <option value="skipped">Skipped</option>
        </select>
      </label>
      <label className="space-y-1">
        <span className="text-muted">Followed the plan?</span>
        <select name="followed_plan" defaultValue={followed} className={inputClass}>
          <option value="">Not yet known</option>
          <option value="yes">Yes</option>
          <option value="no">No, deviated</option>
        </select>
      </label>
      <label className="space-y-1">
        <span className="text-muted">Why (skip reason, change made)</span>
        <input name="reason" defaultValue={entry?.reason ?? plan?.reason ?? ""} className={inputClass} />
      </label>
      <label className="space-y-1">
        <span className="text-muted">
          My stop, if not the signal&apos;s{signalStop ? ` (₹${Number(signalStop).toFixed(2)})` : ""}
        </span>
        <input
          name="stop"
          inputMode="decimal"
          defaultValue={entry?.own_stop ? (entry.stop ?? "") : planStop}
          className={inputClass}
        />
      </label>
      <label className="space-y-1 sm:col-span-2">
        <span className="text-muted">Notes</span>
        <textarea name="notes" rows={2} defaultValue={entry?.notes ?? ""} className={inputClass} />
      </label>
      <div>
        <button className={buttonClass}>Save</button>
      </div>
    </form>
  );
}

export function FillForm({
  action,
  today,
  plan,
}: {
  action: (form: FormData) => Promise<void>;
  today: string;
  // Before the first fill, the plan's shares and entry are the starting values.
  plan?: SavedPlan | null;
}) {
  return (
    <form action={action} className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-6">
      <label className="space-y-1">
        <span className="text-muted">Date</span>
        <input type="date" name="trade_date" defaultValue={today} required className={inputClass} />
      </label>
      <label className="space-y-1">
        <span className="text-muted">Side</span>
        <select name="side" className={inputClass}>
          <option value="buy">Buy</option>
          <option value="sell">Sell</option>
        </select>
      </label>
      <label className="space-y-1">
        <span className="text-muted">Shares</span>
        <input name="shares" type="number" min={1} required defaultValue={plan?.shares ?? ""} className={inputClass} />
      </label>
      <label className="space-y-1">
        <span className="text-muted">Price ₹</span>
        <input
          name="price"
          inputMode="decimal"
          required
          defaultValue={plan ? String(Number(plan.entry)) : ""}
          className={inputClass}
        />
      </label>
      <label className="space-y-1">
        <span className="text-muted">Charges ₹</span>
        <input name="charges" inputMode="decimal" defaultValue="0" className={inputClass} />
      </label>
      <div className="flex items-end">
        <button className={buttonClass}>Add fill</button>
      </div>
    </form>
  );
}
