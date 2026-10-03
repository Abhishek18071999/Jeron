import Link from "next/link";

import type { SignalBrief } from "@/lib/api";

export const inr = (value: number | string | null | undefined, digits = 2) => {
  if (value === null || value === undefined || value === "") return "-";
  const n = typeof value === "string" ? Number(value) : value;
  const text = Math.abs(n).toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${n < 0 ? "-" : ""}₹${text}`;
};

export const rMultiple = (value: string | number | null | undefined) => {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}R`;
};

export function Card({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
      <div className="mb-3 flex items-center justify-between gap-4">
        <h2 className="font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function ResearchBadge({ research }: { research: boolean }) {
  return research ? (
    <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
      RESEARCH ONLY
    </span>
  ) : (
    <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-800 dark:bg-green-900/40 dark:text-green-300">
      SIGNAL
    </span>
  );
}

export function SignalRow({ s, action = "Decide" }: { s: SignalBrief; action?: string }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 border-t border-neutral-200 py-2 first:border-t-0 dark:border-neutral-800">
      <div className="flex flex-wrap items-center gap-2">
        <Link href={`/stocks/${s.ticker}`} className="font-medium underline-offset-2 hover:underline">
          {s.ticker}
        </Link>
        <ResearchBadge research={s.research_only} />
        <span className="text-sm text-neutral-500">
          {s.strategy_key} · conviction {s.conviction}/5 · {s.signal_date}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span>
          Buy {inr(s.entry_low)}-{inr(s.entry_high)} · stop {inr(s.stop)} · T1 {inr(s.t1)}
        </span>
        <Link
          href={`/journal/signal/${s.signal_id}`}
          className="rounded border border-neutral-300 px-2 py-0.5 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-900"
        >
          {action}
        </Link>
      </div>
    </li>
  );
}

export function ErrorNote({ error }: { error?: string | string[] }) {
  if (!error) return null;
  return (
    <p className="mb-4 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
      {Array.isArray(error) ? error.join("; ") : error}
    </p>
  );
}

export const inputClass =
  "w-full rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700";
export const buttonClass =
  "rounded bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300";
