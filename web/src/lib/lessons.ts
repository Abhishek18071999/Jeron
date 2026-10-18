// The Learn section: lessons from the basics to Jeron's own strategies, each with goals,
// an everyday picture, worked examples in rupees, a problem to try, a recap and a quiz.
// The lessons live in src/lib/learn/, one file per track. Jeron's numbers (score points,
// fund-v1 points, costs, gates, strategy rules and results) are copied from the backend;
// a change there should change them here: backend/app/scan/score.py,
// app/fundamentals/score.py, app/backtest/costs.py, engine.py, strategies.py,
// stats.py and walkforward.py, app/news/labels.py, and docs/backtests/.
//
// Text may use **bold** and [links](/learn/slug). A diagram block names one of the
// drawings in src/app/learn/diagrams.tsx.
import { BASICS } from "./learn/basics";
import { FUNDAMENTALS } from "./learn/fundamentals";
import { PROCESS } from "./learn/process";
import { STRATEGIES } from "./learn/strategies";
import { TECHNICALS } from "./learn/technicals";
import type { Lesson, TrackKey } from "./learn/types";

export type { Block, Lesson, Question, TrackKey } from "./learn/types";
export { GLOSSARY } from "./learn/glossary";

export const TRACKS: { key: TrackKey; title: string; text: string }[] = [
  {
    key: "basics",
    title: "1. Start here",
    text: "How the market works, charts, corporate actions, and the risk rules that keep you in the game.",
  },
  {
    key: "technicals",
    title: "2. Technical analysis",
    text: "Trends, moving averages, RSI, MACD, ATR, ADX, volume, breakouts, relative strength and the market regime, each calculated by hand.",
  },
  {
    key: "fundamentals",
    title: "3. Fundamental analysis",
    text: "Reading quarterly results: growth, margins, P/E, what makes a business good, and the news that moves prices.",
  },
  {
    key: "strategies",
    title: "4. Strategies in depth",
    text: "How Jeron tests, how every trade runs, and every strategy: the exact rules, a worked signal, how it did and when it fails.",
  },
  {
    key: "process",
    title: "5. Doing it for real",
    text: "Your first trade step by step, the journal, your own psychology, the costly mistakes and realistic expectations.",
  },
];

export const LESSONS: Lesson[] = [...BASICS, ...TECHNICALS, ...FUNDAMENTALS, ...STRATEGIES, ...PROCESS];

export const lessonBySlug = (slug: string) => LESSONS.find((l) => l.slug === slug);
