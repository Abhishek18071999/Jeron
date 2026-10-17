import Link from "next/link";

import { Page, PageHeader } from "@/components/ui";
import { LESSONS, TRACKS } from "@/lib/lessons";

import { DoneMark } from "./quiz";

export const metadata = { title: "Learn · Jeron" };

export default function LearnPage() {
  return (
    <Page>
      <PageHeader
        title="Learn"
        subtitle="Technical and fundamental analysis, risk, and every strategy Jeron runs, explained simply with worked examples in rupees. Start at the top and go in order, or jump to what you need."
      />
      {TRACKS.map((track) => {
        const lessons = LESSONS.filter((l) => l.track === track.key);
        return (
          <section key={track.key} className="space-y-3">
            <div>
              <h2 className="text-lg font-semibold tracking-tight">{track.title}</h2>
              <p className="text-sm text-muted">{track.text}</p>
            </div>
            <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {lessons.map((l) => (
                <li key={l.slug}>
                  <Link
                    href={`/learn/${l.slug}`}
                    className="block h-full rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-surface-2"
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span className="font-semibold">{l.title}</span>
                      <DoneMark slug={l.slug} />
                    </span>
                    <span className="mt-1 block text-sm text-muted">{l.summary}</span>
                    <span className="mt-2 block text-xs text-muted">
                      {l.minutes} min{l.quiz ? " · quiz" : ""}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </section>
        );
      })}
      <p className="text-xs text-muted">
        Education, not advice. Every number here comes from Jeron&apos;s own rules and research; markets change, so
        test before you trust.
      </p>
    </Page>
  );
}
