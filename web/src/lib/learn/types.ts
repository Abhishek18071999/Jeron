// The shapes lessons are written in. Text may use **bold** and [links](/learn/slug).

export type DiagramName =
  | "candle"
  | "trade-plan"
  | "ema-trend"
  | "breakout"
  | "pullback"
  | "drawdown"
  | "gap"
  | "trailing-stop"
  | "streak";

export type Block =
  | { p: string }
  | { h: string }
  | { list: string[] }
  | { steps: string[] }
  // "Think of it like this": the everyday picture before the formula.
  | { analogy: string }
  | { example: { title: string; rows?: [string, string][]; lines?: string[]; result?: string } }
  | { table: { head: string[]; rows: string[][] } }
  | { tip: string }
  | { warn: string }
  // "Your turn": a problem to work out, with the worked answer behind a tap.
  | { try: { q: string; work: string[]; a: string } }
  // "Remember": the lesson in a few lines, at the end.
  | { recap: string[] }
  | { diagram: DiagramName };

export type Question = { q: string; options: string[]; answer: number; why: string };

export type TrackKey = "basics" | "technicals" | "fundamentals" | "strategies" | "process";

export type Lesson = {
  slug: string;
  track: TrackKey;
  title: string;
  summary: string;
  minutes: number;
  // "By the end you can": what the reader will be able to do.
  goals: string[];
  blocks: Block[];
  quiz: Question[];
};
