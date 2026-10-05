import Link from "next/link";

import { Page, PageHeader } from "@/components/ui";

const PAGES = [
  {
    href: "/scanner",
    title: "Scanner",
    text: "Today's universe ranked by the technical score, with every component explained.",
  },
  {
    href: "/backtests",
    title: "Backtests",
    text: "Out-of-sample, after-cost report cards per strategy, and whether each passed the bar.",
  },
  {
    href: "/paper",
    title: "Paper trading",
    text: "One account per strategy version, replayed daily; where signals come from.",
  },
  {
    href: "/compare",
    title: "Backtest vs paper vs real",
    text: "Does each strategy behave live as it did in the backtest? Gates, ranges and causes of drift.",
  },
  {
    href: "/data",
    title: "Data quality",
    text: "Coverage, the daily quality report and whether the scan was allowed to run.",
  },
  {
    href: "/spot-check",
    title: "Spot check",
    text: "Raw vs adjusted prices and indicators for any stock and date, to compare with your broker.",
  },
];

export default function Research() {
  return (
    <Page>
      <PageHeader
        title="Research"
        subtitle="The evidence behind every signal: how stocks are found, tested and checked."
      />
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {PAGES.map((p) => (
          <li key={p.href}>
            <Link
              href={p.href}
              className="block h-full rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-surface-2"
            >
              <span className="font-semibold">{p.title}</span>
              <span className="mt-1 block text-sm text-muted">{p.text}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Page>
  );
}
