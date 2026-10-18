import Link from "next/link";

import { Badge, Card, EmptyState, type Tone, shortDate } from "@/components/ui";
import type { NewsItem, NewsView } from "@/lib/api";

const EVENT_NAMES: Record<string, string> = {
  results: "Results",
  guidance: "Guidance",
  order_win: "Order win",
  regulatory_action: "Regulator",
  promoter_activity: "Promoter",
  rating_change: "Rating",
  management_change: "Management",
  litigation: "Litigation",
  corporate_action: "Corporate action",
  other: "Other",
};

function sentimentBadge(s: number | null): { tone: Tone; text: string } | null {
  if (s === null) return null;
  if (s >= 2) return { tone: "good", text: "very good" };
  if (s === 1) return { tone: "good", text: "good" };
  if (s === 0) return { tone: "neutral", text: "neutral" };
  if (s === -1) return { tone: "bad", text: "bad" };
  return { tone: "bad", text: "very bad" };
}

function Row({ item, showSymbol }: { item: NewsItem; showSymbol: boolean }) {
  const badge = sentimentBadge(item.sentiment);
  return (
    <li className="border-t border-line py-2 first:border-t-0 first:pt-0">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
        <span>{shortDate(item.day)}</span>
        {showSymbol && (
          <Link href={`/stocks/${item.symbol}`} className="font-semibold text-fg hover:underline">
            {item.symbol}
          </Link>
        )}
        <Badge>{EVENT_NAMES[item.event_type] ?? item.event_type}</Badge>
        {badge && <Badge tone={badge.tone}>{badge.text}</Badge>}
      </p>
      <p className="mt-1 text-sm">{item.subject ? <span className="font-medium">{item.subject}: </span> : null}{item.text}</p>
      {item.sentiment !== null && item.reason && <p className="mt-0.5 text-xs text-muted">{item.reason}</p>}
    </li>
  );
}

export function NewsCard({
  title,
  news,
  showSymbol = false,
  empty,
}: {
  title: string;
  news: NewsView | null;
  showSymbol?: boolean;
  empty: string;
}) {
  const subtitle =
    news?.score !== null && news?.score !== undefined
      ? `News score ${news.score.toFixed(0)} (50 is neutral; below 40 keeps the news-filtered strategies out)`
      : undefined;
  return (
    <Card title={title} subtitle={subtitle}>
      {!news ? (
        <EmptyState>The news couldn&apos;t be loaded.</EmptyState>
      ) : news.items.length === 0 ? (
        <EmptyState>
          {empty} <Link href="/setup" className="underline">Setup</Link> shows what Jeron is reading.
        </EmptyState>
      ) : (
        <ul className="max-h-[28rem] overflow-y-auto pr-1">
          {news.items.map((item, i) => (
            <Row key={`${item.symbol}-${item.day}-${i}`} item={item} showSymbol={showSymbol} />
          ))}
        </ul>
      )}
      {news?.note && (
        <p className="mt-3 text-xs text-muted">
          {news.note}{" "}
          {!news.labeller_ready && (
            <Link href="/setup" className="underline">
              How to add one
            </Link>
          )}
        </p>
      )}
    </Card>
  );
}
