import { Page, PageHeader } from "@/components/ui";

// Shown while the briefs and prices load (each stock's history is adjusted on read).
export default function Loading() {
  return (
    <Page>
      <PageHeader title="Compare stocks" subtitle="Building the comparison…" />
      <div className="grid animate-pulse gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-44 rounded-xl border border-line bg-surface-2" />
        ))}
      </div>
      <div className="h-80 animate-pulse rounded-xl border border-line bg-surface-2" />
    </Page>
  );
}
