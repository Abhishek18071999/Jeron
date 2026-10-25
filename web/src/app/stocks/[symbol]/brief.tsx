import { SignalHowTo } from "@/components/strategy-guide";
import { Badge, Card, Notice, type Tone, shortDate } from "@/components/ui";
import type { BriefFact, ExplainView, StockBrief } from "@/lib/api";

import { Narrate } from "./narrate";

const kindText: Record<BriefFact["kind"], string> = {
  data: "exchange data",
  calculated: "Jeron's calculation",
  model: "a model's reading",
  rule: "the strategy's rule",
};

const checkTone: Record<string, Tone> = { pass: "good", fail: "bad", unknown: "neutral" };
const setupTone: Record<string, Tone> = {
  "in zone": "good",
  waiting: "accent",
  "above zone": "warn",
  invalidated: "bad",
  expired: "bad",
};

export function FactLine({ f }: { f: BriefFact }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-1.5">
      <span className="font-mono text-[0.7rem] text-muted">{f.id}</span>
      <span>{f.label}:</span>
      <span className="font-medium">{f.value}</span>
      <span className="text-xs text-muted">
        ({kindText[f.kind]}, {f.source}
        {f.as_of ? `, ${shortDate(f.as_of)}` : ""})
      </span>
    </li>
  );
}

function FactList({ ids, brief, empty }: { ids: string[]; brief: StockBrief; empty: string }) {
  const facts = ids.map((id) => brief.facts.find((f) => f.id === id)).filter((f): f is BriefFact => !!f);
  if (!facts.length) return <p className="text-muted">{empty}</p>;
  return (
    <ul className="space-y-1">
      {facts.map((f) => (
        <FactLine key={f.id} f={f} />
      ))}
    </ul>
  );
}

export function BriefCard({ view }: { view: ExplainView }) {
  const b = view.brief;
  return (
    <Card
      title="Explain this stock"
      subtitle={`From Jeron's own numbers${b.as_of ? `, as of ${shortDate(b.as_of)}` : ""}. Each line says where it comes from. Not advice: you decide.`}
      action={
        b.setup && (
          <Badge tone={setupTone[b.setup.state] ?? "neutral"} title={b.setup.reasons.join("; ")}>
            setup: {b.setup.state}
          </Badge>
        )
      }
    >
      <div className="space-y-4 text-sm">
        {b.stale && (
          <Notice tone="warn">
            The newest prices are not the latest session&apos;s: read this as of {shortDate(b.as_of)}.
          </Notice>
        )}
        {b.setup && (
          <p>
            <span className="font-medium">Is the signal still valid? </span>
            {b.setup.still_valid ? "Yes" : "No"}: {b.setup.reasons.join("; ")}.
          </p>
        )}
        {b.strategy && (
          <div className="rounded-lg border border-line bg-surface-2 p-3">
            <h3 className="mb-1 font-medium">How to use this signal</h3>
            <SignalHowTo brief={b} compact />
          </div>
        )}
        {b.why_in_scan.length > 0 && (
          <div>
            <h3 className="mb-1 font-medium">Why it is in the scan</h3>
            <ul className="list-disc space-y-0.5 pl-5">
              {b.why_in_scan.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <h3 className="mb-1 font-medium text-good">What supports it</h3>
            <FactList ids={b.supporting} brief={b} empty="Nothing in Jeron's numbers." />
          </div>
          <div>
            <h3 className="mb-1 font-medium text-bad">What argues against it</h3>
            <FactList ids={b.against} brief={b} empty="Nothing in Jeron's numbers." />
          </div>
        </div>
        {b.cancels.length > 0 && (
          <div>
            <h3 className="mb-1 font-medium">What would cancel the setup</h3>
            <ul className="list-disc space-y-0.5 pl-5">
              {b.cancels.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
        )}
        {Object.keys(b.scenarios).length > 0 && (
          <div>
            <h3 className="mb-1 font-medium">Scenarios (price levels, not forecasts)</h3>
            <ul className="space-y-0.5">
              {(["bullish", "neutral", "bearish"] as const).map(
                (k) =>
                  b.scenarios[k] && (
                    <li key={k}>
                      <span className="capitalize text-muted">{k}: </span>
                      {b.scenarios[k]}
                    </li>
                  ),
              )}
            </ul>
          </div>
        )}
        <div>
          <h3 className="mb-1 font-medium">Before a trade</h3>
          <ul className="space-y-1">
            {b.checklist.map((c) => (
              <li key={c.label} className="flex flex-wrap items-center gap-2">
                <Badge tone={checkTone[c.status]}>{c.status}</Badge>
                <span>{c.label}</span>
                <span className="text-xs text-muted">{c.detail}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-1 font-medium">What Jeron doesn&apos;t know</h3>
          <ul className="list-disc space-y-0.5 pl-5 text-muted">
            {b.unknowns.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </div>
        <details>
          <summary className="cursor-pointer font-medium">All {b.facts.length} facts, with sources</summary>
          <ul className="mt-2 space-y-1">
            {b.facts.map((f) => (
              <FactLine key={f.id} f={f} />
            ))}
          </ul>
        </details>
        <Narrate symbol={b.symbol} facts={b.facts} stored={view.narration} writer={view.writer} />
      </div>
    </Card>
  );
}
