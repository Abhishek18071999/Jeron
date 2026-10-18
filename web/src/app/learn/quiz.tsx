"use client";

import Link from "next/link";
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

const readRaw = () => {
  try {
    return localStorage.getItem(KEY) ?? "[]";
  } catch {
    return "[]";
  }
};

// "7 of 34 done" with a bar, and a link to the first lesson not done yet.
export function Progress({ lessons }: { lessons: { slug: string; title: string }[] }) {
  const raw = useSyncExternalStore(noSubscribe, readRaw, () => null);
  if (raw === null) return null;
  let done: string[] = [];
  try {
    const value = JSON.parse(raw);
    done = Array.isArray(value) ? value : [];
  } catch {
    done = [];
  }
  const count = lessons.filter((l) => done.includes(l.slug)).length;
  const next = lessons.find((l) => !done.includes(l.slug));
  const pct = Math.round((count / lessons.length) * 100);
  return (
    <div className="space-y-2 rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">
          {count} of {lessons.length} lessons done
        </span>
        {next ? (
          <Link href={`/learn/${next.slug}`} className="font-medium text-accent hover:underline">
            {count === 0 ? "Start" : "Continue"}: {next.title} →
          </Link>
        ) : (
          <span className="text-good">All done. Revisit any lesson when a signal puzzles you.</span>
        )}
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
