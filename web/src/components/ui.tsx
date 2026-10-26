// The design system: small building blocks every page shares. Colours come from the
// tokens in globals.css (good/bad for gains and losses, accent for "act now", warn for
// limits). Server components; the interactive parts live in explain.tsx.
import Link from "next/link";

import { Command, Explain } from "@/components/explain";

import type { SignalBrief } from "@/lib/api";
import { strategyGuide } from "@/lib/strategy-guide";

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

// One date style everywhere: "Fri, 9 Oct", with the year only when it isn't this year.
export const shortDate = (iso: string | null | undefined) => {
  if (!iso) return "-";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  const thisYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(thisYear ? {} : { year: "numeric" }),
  });
};

// The command that fills an empty screen, as typed on the machine running Jeron.
export const cli = (job: string) => `docker compose exec backend python -m app.cli ${job}`;

// "Run <command>" on a computer; on a phone, which can't run it, a plain sentence.
export function RunCommand({
  job,
  lead = "Run",
  phone = "Jeron's evening run fills this in.",
}: {
  job: string;
  lead?: string;
  phone?: string;
}) {
  return (
    <>
      <span className="sm:hidden">{phone}</span>
      <span className="hidden sm:inline">{lead} </span>
      <Command command={cli(job)} />
    </>
  );
}

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

// A "?" that opens the plain-English explanation; a phone-sized tap target.
export function Help({ text, title = "What this means", how }: { text: string; title?: React.ReactNode; how?: string }) {
  return (
    <Explain title={title} text={text} how={how} className="-my-1 ml-0.5 inline-flex h-6 w-6 items-center justify-center align-middle no-underline hover:no-underline">
      <span aria-label={text} className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-line-strong text-[0.6rem] font-semibold text-muted">
        ?
      </span>
    </Explain>
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
  how,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: Tone;
  help?: string;
  how?: string;
}) {
  const shown = <span className={`block truncate text-xl font-semibold tracking-tight ${statTones[tone]}`}>{value}</span>;
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted">{label}</p>
      {/* Tap the number itself to see what it means. */}
      <div className="mt-0.5 min-w-0">
        {help ? (
          <Explain title={<>{label}: {value}</>} text={help} how={how} className="block max-w-full">
            {shown}
          </Explain>
        ) : (
          shown
        )}
      </div>
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

// Every empty screen says what fills it: Jeron runs these jobs by itself (the Setup
// page shows progress); the command is there for running one by hand.
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
          Jeron does this by itself while it runs; <Link href="/setup" className="underline">Setup</Link> shows
          progress.<span className="sm:hidden"> Nothing to type on your phone.</span>
          <span className="hidden sm:inline"> To run it now by hand: </span>
          <Command command={command} />
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

// `stack`: on phones each row becomes a small card (give every Td a `label`), so the
// table never scrolls sideways.
export function Table({
  children,
  className = "",
  stack = false,
}: {
  children: React.ReactNode;
  className?: string;
  stack?: boolean;
}) {
  return (
    <div className={stack ? "sm:-mx-5 sm:overflow-x-auto sm:px-5" : "-mx-4 overflow-x-auto px-4 sm:-mx-5 sm:px-5"}>
      <table className={`w-full border-collapse text-sm ${stack ? "stack-table" : ""} ${className}`}>{children}</table>
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
  label,
}: {
  children?: React.ReactNode;
  num?: boolean;
  className?: string;
  title?: string;
  // The column's name, shown beside the value when a `stack` table is a card.
  label?: string;
}) {
  return (
    <td
      title={title}
      data-label={label ?? ""}
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

// A strategy key that opens its Learn lesson, when it has one.
export function StrategyLink({ strategy }: { strategy: string }) {
  const found = strategyGuide(strategy);
  if (!found) return <>{strategy}</>;
  return (
    <Link href={`/learn/${found.guide.lesson}`} title={`${found.guide.name}: how it works and how to act on it`} className="underline decoration-dotted">
      {strategy}
    </Link>
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
          <StrategyLink strategy={s.strategy_key} /> · conviction {s.conviction}/5 · {shortDate(s.signal_date)}
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
