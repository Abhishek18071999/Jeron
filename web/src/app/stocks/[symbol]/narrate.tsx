"use client";

import { useActionState } from "react";

import { Button, Notice, inputClass } from "@/components/ui";
import type { ApiResult, BriefFact, ExplainView, Narration } from "@/lib/api";

import { narrateStock } from "./actions";

function Points({ n, facts }: { n: Narration; facts: BriefFact[] }) {
  if (n.status !== "ok") {
    return (
      <Notice tone="warn">
        {n.status === "failed" ? "The LLM provider answered with an error: " : "The LLM's wording was refused: "}
        {n.problems.join("; ")}. The brief above stands on its own.
      </Notice>
    );
  }
  const label = (id: string) => facts.find((f) => f.id === id);
  return (
    <div className="space-y-1.5">
      {n.question && <p className="text-muted">Q: {n.question}</p>}
      <ul className="space-y-1.5">
        {n.points.map((p) => (
          <li key={p.text}>
            {p.text}{" "}
            {p.facts.map((id) => (
              <span
                key={id}
                title={label(id) ? `${label(id)?.label}: ${label(id)?.value} (${label(id)?.source})` : id}
                className="ml-0.5 rounded bg-surface-2 px-1 font-mono text-[0.65rem] text-muted"
              >
                {id}
              </span>
            ))}
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted">
        Worded by {n.model} ({n.prompt_version}) from the facts above only; every number was checked against the
        facts it cites.
      </p>
    </div>
  );
}

export function Narrate({
  symbol,
  facts,
  stored,
  writer,
}: {
  symbol: string;
  facts: BriefFact[];
  stored: Narration | null;
  writer: ExplainView["writer"];
}) {
  const [result, action, pending] = useActionState<ApiResult<Narration> | null, FormData>(
    narrateStock.bind(null, symbol),
    null,
  );
  const shown = result?.ok ? result.data : stored;
  return (
    <div className="space-y-2 border-t border-line pt-3">
      <h3 className="font-medium">In plain words (optional, uses the LLM)</h3>
      {shown && <Points n={shown} facts={facts} />}
      {result && !result.ok && <Notice tone="bad">{result.error}</Notice>}
      {writer.ready ? (
        <form action={action} className="flex flex-col gap-2 sm:flex-row">
          <input
            name="question"
            maxLength={300}
            placeholder="Optional question, e.g. what argues against it?"
            className={inputClass}
          />
          <Button type="submit" variant="secondary" disabled={pending}>
            {pending ? "Asking…" : shown ? "Ask" : "Explain in words"}
          </Button>
        </form>
      ) : (
        <p className="text-xs text-muted">{writer.note ?? "The LLM is not available."}</p>
      )}
      <p className="text-xs text-muted">
        This month: about US${Number(writer.budget_spent_usd).toFixed(2)} of the US$
        {Number(writer.budget_cap_usd).toFixed(2)} LLM cap (shared with news labels).
      </p>
    </div>
  );
}
