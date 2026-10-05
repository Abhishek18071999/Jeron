import type { JournalEntry } from "@/lib/api";
import { buttonClass, inputClass } from "@/components/ui";

export function PlanForm({
  action,
  entry,
  signalStop,
}: {
  action: (form: FormData) => Promise<void>;
  entry?: JournalEntry | null;
  signalStop?: string | null;
}) {
  const followed = entry?.followed_plan === true ? "yes" : entry?.followed_plan === false ? "no" : "";
  return (
    <form action={action} className="grid gap-3 text-sm sm:grid-cols-2">
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
        <input name="reason" defaultValue={entry?.reason ?? ""} className={inputClass} />
      </label>
      <label className="space-y-1">
        <span className="text-muted">
          My stop, if not the signal&apos;s{signalStop ? ` (₹${Number(signalStop).toFixed(2)})` : ""}
        </span>
        <input
          name="stop"
          inputMode="decimal"
          defaultValue={entry?.own_stop ? (entry.stop ?? "") : ""}
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

export function FillForm({ action, today }: { action: (form: FormData) => Promise<void>; today: string }) {
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
        <input name="shares" type="number" min={1} required className={inputClass} />
      </label>
      <label className="space-y-1">
        <span className="text-muted">Price ₹</span>
        <input name="price" inputMode="decimal" required className={inputClass} />
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
