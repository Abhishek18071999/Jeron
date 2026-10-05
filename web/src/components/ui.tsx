// The design system: small building blocks every page shares. Colours come from the
// tokens in globals.css (good/bad for gains and losses, accent for "act now", warn for
// limits). Server components only; no client state here.
import Link from "next/link";

import type { SignalBrief } from "@/lib/api";

// --- Formatting -----------------------------------------------------------------------

export const inr = (value: number | string | null | undefined, digits = 2) => {
  if (value === null || value === undefined || value === "") return "-";
  const n = typeof value === "string" ? Number(value) : value;
  const text = Math.abs(n).toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${n < 0 ? "-" : ""}₹${text}`;
};

// Signed rupees for P&L: +₹1,200 / -₹300.
export const inrSigned = (value: number | string | null | undefined, digits = 0) => {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  return `${n > 0 ? "+" : ""}${inr(n, digits)}`;
};

export const rMultiple = (value: string | number | null | undefined) => {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}R`;
};

export const pctText = (value: number | string | null | undefined, digits = 1, signed = false) => {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  return `${signed && n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
};

// Gains green, losses red, zero and unknown neutral.
export const signTone = (value: number | string | null | undefined) => {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  return n > 0 ? "text-good" : n < 0 ? "text-bad" : "";
};

export const shortDate = (iso: string | null | undefined) => {
  if (!iso) return "-";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
};

// The command that fills an empty screen, as typed on the machine running Jeron.
export const cli = (job: string) => `docker compose exec backend python -m app.cli ${job}`;

// --- Layout ---------------------------------------------------------------------------

export function Page({
  children,
  width = "wide",
}: {
  children: React.ReactNode;
  width?: "wide" | "narrow";
}) {
  return (
    <main className={`mx-auto ${width === "wide" ? "max-w-6xl" : "max-w-3xl"} space-y-5 px-4 py-5 sm:py-6`}>
      {children}
    </main>
  );
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}

export function Card({
  title,
  subtitle,
  children,
  action,
  className = "",
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5 ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-start justify-between gap-4">
          <div className="min-w-0">
            {title && <h2 className="text-[0.95rem] font-semibold leading-6">{title}</h2>}
            {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
          </div>
          {action && <div className="shrink-0 text-sm">{action}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

// --- Small parts ----------------------------------------------------------------------

export type Tone = "neutral" | "good" | "bad" | "accent" | "warn";

const badgeTones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted",
  good: "bg-good-bg text-good",
  bad: "bg-bad-bg text-bad",
  accent: "bg-accent-bg text-accent",
  warn: "bg-warn-bg text-warn",
};

export function Badge({
  tone = "neutral",
  children,
  title,
}: {
  tone?: Tone;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide ${badgeTones[tone]}`}
    >
      {children}
    </span>
  );
}

// A small "?" whose tooltip explains a number in plain English.
export function Help({ text }: { text: string }) {
  return (
    <span
      title={text}
      aria-label={text}
      tabIndex={0}
      className="ml-1 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-line-strong align-middle text-[0.6rem] font-semibold text-muted"
    >
      ?
    </span>
  );
}

const statTones: Record<Tone, string> = {
  neutral: "",
  good: "text-good",
  bad: "text-bad",
  accent: "text-accent",
  warn: "text-warn",
};

export function Stat({
  label,
  value,
  sub,
  tone = "neutral",
  help,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: Tone;
  help?: string;
}) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted">
        {label}
        {help && <Help text={help} />}
      </p>
      <p className={`mt-0.5 truncate text-xl font-semibold tracking-tight ${statTones[tone]}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
    </div>
  );
}

const buttonVariants = {
  primary: "bg-accent text-accent-fg hover:opacity-90",
  secondary: "border border-line-strong bg-surface hover:bg-surface-2",
  ghost: "text-muted hover:bg-surface-2 hover:text-fg",
};

export type ButtonVariant = keyof typeof buttonVariants;

const buttonBase =
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50";

export function Button({
  variant = "secondary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button className={`${buttonBase} ${buttonVariants[variant]} ${className}`} {...props} />;
}

export function LinkButton({
  href,
  variant = "secondary",
  children,
  className = "",
}: {
  href: string;
  variant?: ButtonVariant;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Link href={href} className={`${buttonBase} ${buttonVariants[variant]} ${className}`}>
      {children}
    </Link>
  );
}

// "Run this to fill it": every empty screen says which command fills it.
export function EmptyState({
  children,
  command,
}: {
  children: React.ReactNode;
  command?: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong px-3 py-3 text-sm text-muted">
      <p>{children}</p>
      {command && (
        <p className="mt-1.5">
          Run <code>{command}</code>
        </p>
      )}
    </div>
  );
}

const noticeTones: Record<Tone, string> = {
  neutral: "border-line bg-surface-2",
  good: "border-good/30 bg-good-bg",
  bad: "border-bad/30 bg-bad-bg text-bad",
  accent: "border-accent/30 bg-accent-bg",
  warn: "border-warn/30 bg-warn-bg",
};

export function Notice({ tone = "neutral", children }: { tone?: Tone; children: React.ReactNode }) {
  return <div className={`rounded-lg border px-3 py-2 text-sm ${noticeTones[tone]}`}>{children}</div>;
}

// --- Tables ---------------------------------------------------------------------------

export function Table({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4 sm:-mx-5 sm:px-5">
      <table className={`w-full border-collapse text-sm ${className}`}>{children}</table>
    </div>
  );
}

export function Th({
  children,
  num = false,
  help,
  className = "",
}: {
  children?: React.ReactNode;
  num?: boolean;
  help?: string;
  className?: string;
}) {
  return (
    <th
      className={`whitespace-nowrap border-b border-line py-2 pr-3 text-xs font-medium text-muted last:pr-0 ${num ? "text-right" : "text-left"} ${className}`}
    >
      {children}
      {help && <Help text={help} />}
    </th>
  );
}

export function Td({
  children,
  num = false,
  className = "",
  title,
}: {
  children?: React.ReactNode;
  num?: boolean;
  className?: string;
  title?: string;
}) {
  return (
    <td
      title={title}
      className={`border-b border-line py-2 pr-3 align-top last:pr-0 ${num ? "whitespace-nowrap text-right" : ""} ${className}`}
    >
      {children}
    </td>
  );
}

// --- Signals and notes (shared by several pages) --------------------------------------

export function ResearchBadge({ research }: { research: boolean }) {
  return research ? (
    <Badge tone="neutral" title="From a strategy that has not passed the backtest bar: paper-traded for evidence, not a trade">
      Research only
    </Badge>
  ) : (
    <Badge tone="accent" title="From a strategy that passed the backtest bar">
      Signal
    </Badge>
  );
}

export function SignalRow({ s, action = "Decide" }: { s: SignalBrief; action?: string }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2.5 first:border-t-0">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Link href={`/stocks/${s.ticker}`} className="font-semibold hover:underline">
          {s.ticker}
        </Link>
        <ResearchBadge research={s.research_only} />
        <span className="text-xs text-muted">
          {s.strategy_key} · conviction {s.conviction}/5 · {s.signal_date}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span>
          Buy {inr(s.entry_low)}–{inr(s.entry_high)} · stop {inr(s.stop)} · T1 {inr(s.t1)}
        </span>
        <LinkButton href={`/journal/signal/${s.signal_id}`} variant={s.research_only ? "secondary" : "primary"}>
          {action}
        </LinkButton>
      </div>
    </li>
  );
}

export function ErrorNote({ error }: { error?: string | string[] }) {
  if (!error) return null;
  return (
    <div className="mb-4">
      <Notice tone="bad">{Array.isArray(error) ? error.join("; ") : error}</Notice>
    </div>
  );
}

export const inputClass =
  "w-full rounded-lg border border-line-strong bg-surface px-2.5 py-1.5 text-sm placeholder:text-muted";
export const buttonClass = `${buttonBase} ${buttonVariants.primary}`;
