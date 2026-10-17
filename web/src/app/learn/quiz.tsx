"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import type { Question } from "@/lib/lessons";

const KEY = "jeron-learn-done";

export function readDone(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function markDone(slug: string) {
  try {
    const done = new Set(readDone());
    done.add(slug);
    localStorage.setItem(KEY, JSON.stringify([...done]));
  } catch {
    // Private mode: progress just isn't remembered.
  }
}

export function Quiz({ slug, questions }: { slug: string; questions: Question[] }) {
  const [picked, setPicked] = useState<(number | null)[]>(questions.map(() => null));
  const right = picked.filter((p, i) => p === questions[i].answer).length;
  useEffect(() => {
    if (questions.length && right === questions.length) markDone(slug);
  }, [right, questions.length, slug]);
  return (
    <div className="space-y-4">
      {questions.map((q, i) => (
        <div key={q.q}>
          <p className="font-medium">{q.q}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {q.options.map((o, j) => {
              const chosen = picked[i] === j;
              const tone = chosen ? (j === q.answer ? "border-good bg-good-bg text-good" : "border-bad bg-bad-bg text-bad") : "border-line-strong hover:bg-surface-2";
              return (
                <button
                  key={o}
                  type="button"
                  onClick={() => setPicked((p) => p.map((v, k) => (k === i ? j : v)))}
                  className={`rounded-lg border px-3 py-1.5 text-sm ${tone}`}
                >
                  {o}
                </button>
              );
            })}
          </div>
          {picked[i] !== null && (
            <p className={`mt-1.5 text-sm ${picked[i] === q.answer ? "text-good" : "text-bad"}`}>
              {picked[i] === q.answer ? "Right. " : "Not quite. "}
              <span className="text-muted">{q.why}</span>
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

// Marks a lesson without a quiz as read once it is opened.
export function MarkRead({ slug }: { slug: string }) {
  useEffect(() => markDone(slug), [slug]);
  return null;
}

const noSubscribe = () => () => {};

export function DoneMark({ slug }: { slug: string }) {
  const done = useSyncExternalStore(
    noSubscribe,
    () => readDone().includes(slug),
    () => false,
  );
  return done ? <span className="text-xs font-medium text-good">✓ done</span> : null;
}
