"use client";

// The morning briefing's tick boxes: what I've done stays ticked for the day on this
// device (browser storage), and the card says when everything is done.
import Link from "next/link";
import { useEffect, useState } from "react";

import type { BriefItem, BriefKind } from "@/lib/briefing";

const kindTone: Record<BriefKind, string> = {
  sell: "text-bad",
  check: "text-warn",
  buy: "text-accent",
  record: "text-fg",
  cash: "text-fg",
};

function load(key: string): string[] {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

export function BriefingList({ day, items }: { day: string; items: BriefItem[] }) {
  const key = `jeron:briefing:${day}`;
  const [done, setDone] = useState<string[]>([]);
  useEffect(() => {
    // Read after mount: the server render can't see this device's ticks.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDone(load(key));
  }, [key]);
  const toggle = (id: string) => {
    const next = done.includes(id) ? done.filter((d) => d !== id) : [...done, id];
    setDone(next);
    try {
      window.localStorage.setItem(key, JSON.stringify(next));
    } catch {
      // Private mode: ticks last until the page reloads.
    }
    if (!done.includes(id)) navigator.vibrate?.(15);
  };
  const left = items.filter((i) => !done.includes(i.id)).length;
  return (
    <div>
      {left === 0 ? (
        <p className="mb-2 rounded-lg bg-good-bg px-3 py-2 text-sm font-medium text-good">
          ✓ Done for today. Nothing left before the open.
        </p>
      ) : (
        <p className="mb-2 text-xs text-muted">
          {items.length - left} of {items.length} done
        </p>
      )}
      <ul className="space-y-1">
        {items.map((i) => {
          const ticked = done.includes(i.id);
          return (
            <li key={i.id} className="flex items-start gap-3 rounded-lg py-1.5">
              <button
                type="button"
                role="checkbox"
                aria-checked={ticked}
                aria-label={`Mark "${i.title}" done`}
                onClick={() => toggle(i.id)}
                className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-sm ${
                  ticked ? "border-good bg-good text-accent-fg" : "border-line-strong"
                }`}
              >
                {ticked ? "✓" : ""}
              </button>
              <div className={`min-w-0 ${ticked ? "opacity-50" : ""}`}>
                <Link href={i.href} className={`font-semibold hover:underline ${ticked ? "line-through" : kindTone[i.kind]}`}>
                  {i.title}
                </Link>
                <p className="text-xs text-muted">{i.detail}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
