import Link from "next/link";

import { Badge } from "@/components/ui";
import type { StockBrief } from "@/lib/api";
import { EVENTS_RULE, GUIDES, SECTION_RULES, howToAct, strategyGuide } from "@/lib/strategy-guide";

const factValue = (b: StockBrief, label: string) => b.facts.find((f) => f.topic === "signal" && f.label === label)?.value;

// "How to use this signal": what the strategy looks for, when it works, and the steps
// from signal to exit, with this signal's own levels. Nothing when there is no signal.
export function SignalHowTo({ brief, compact = false }: { brief: StockBrief; compact?: boolean }) {
  const found = strategyGuide(brief.strategy);
  if (!brief.strategy) return null;
  if (!found) {
    return (
      <p className="text-sm text-muted">
        Signal from {brief.strategy}. See <Link href="/learn/signals-and-exits" className="underline">from signal to exit</Link> for how every Jeron trade runs.
      </p>
    );
  }
  const { guide, events } = found;
  const section = SECTION_RULES[guide.section];
  const zone = factValue(brief, "Entry zone")?.split(",")[0];
  const stop = factValue(brief, "Stop")?.split(":")[0];
  const targets = factValue(brief, "Targets");
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{guide.name}</span>
        <Link href={section.href}>
          <Badge tone="accent">{section.label}</Badge>
        </Link>
        {brief.research_only ? (
          <Badge title="The strategy has not passed all seven backtest checks: paper-traded for evidence, not for real money">research only</Badge>
        ) : (
          <Badge tone="good" title="The strategy passed all seven backtest checks">live</Badge>
        )}
      </div>
      <p>
        <span className="text-muted">Looks for: </span>
        {guide.lookFor}
      </p>
      {!compact && (
        <p>
          <span className="text-muted">When it works: </span>
          {guide.works} Holds for {section.hold}.
        </p>
      )}
      {events && <p className="text-muted">{EVENTS_RULE}</p>}
      {brief.setup && !brief.setup.still_valid && (
        <p className="text-bad">
          This signal&apos;s setup is {brief.setup.state}: there is nothing to act on now. The steps are for the strategy&apos;s next signal.
        </p>
      )}
      {brief.research_only && (
        <p className="text-warn">
          Research only: Jeron paper-trades it to gather evidence, and its rules say not to put real money on it until it passes.
        </p>
      )}
      <details open={!compact}>
        <summary className="cursor-pointer font-medium">How to act on it</summary>
        <ol className="mt-1 list-decimal space-y-0.5 pl-5">
          {howToAct(guide, { zone, stop, targets }).map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
        <p className="mt-1">
          <span className="text-muted">Keep an eye on: </span>
          {guide.watch}
        </p>
      </details>
      <p className="flex flex-wrap gap-x-3 gap-y-1">
        <Link href={`/learn/${guide.lesson}`} className="underline">
          The strategy, worked through
        </Link>
        <Link href="/learn/signals-and-exits" className="underline">
          From signal to exit
        </Link>
        <Link href={`/plan/${brief.symbol}`} className="underline">
          Trade plan for {brief.symbol}
        </Link>
      </p>
    </div>
  );
}

// Every strategy in one table: what it looks for, its section, and its lesson.
export function StrategiesAtAGlance() {
  return (
    <ul className="divide-y divide-line text-sm">
      {GUIDES.map((g) => {
        const section = SECTION_RULES[g.section];
        return (
          <li key={g.key} className="py-2.5 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{g.name}</span>
              <span className="font-mono text-xs text-muted">{g.key}</span>
              <Badge tone="accent">{section.label}</Badge>
            </div>
            <p className="mt-0.5">{g.lookFor}</p>
            <p className="mt-0.5 text-muted">
              {g.works} Holds for {section.hold}.{g.exit ? ` ${g.exit}` : ""}{" "}
              <Link href={`/learn/${g.lesson}`} className="whitespace-nowrap text-fg underline">
                Lesson
              </Link>
            </p>
          </li>
        );
      })}
    </ul>
  );
}
