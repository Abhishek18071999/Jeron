import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import { getJson, type QualityReport } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function QualityReportPage({
  params,
}: {
  params: Promise<{ date: string }>;
}) {
  const { date } = await params;
  const report = await getJson<QualityReport>(`/data/quality/${encodeURIComponent(date)}`);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <Link href="/data" className="text-sm underline">
        All reports
      </Link>
      <h1 className="mt-2 text-2xl font-semibold">Data quality on {date}</h1>
      {!report.ok ? (
        <p className="mt-4 text-red-600">{report.error}</p>
      ) : (
        <div className="mt-6 space-y-4">
          {report.data.checks.map((check) => (
            <section
              key={check.name}
              className="rounded-lg border border-neutral-200 px-4 py-3 dark:border-neutral-800"
            >
              <div className="flex items-center gap-3">
                <StatusBadge status={check.status} />
                <span>{check.message}</span>
              </div>
              {check.items.length > 0 && (
                <ItemsTable items={check.items} total={check.item_count} date={date} />
              )}
            </section>
          ))}
        </div>
      )}
    </main>
  );
}

function ItemsTable({
  items,
  total,
  date,
}: {
  items: Record<string, string>[];
  total: number;
  date: string;
}) {
  const columns = Array.from(new Set(items.flatMap((i) => Object.keys(i))));
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-neutral-500">
          <tr>
            {columns.map((c) => (
              <th key={c} className="pr-4">
                {c.replaceAll("_", " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr key={i} className="border-t border-neutral-200 dark:border-neutral-800">
              {columns.map((c) => (
                <td key={c} className="py-1 pr-4">
                  {c === "symbol" ? (
                    <Link
                      className="underline"
                      href={`/spot-check?symbol=${encodeURIComponent(item[c])}&date=${date}`}
                    >
                      {item[c]}
                    </Link>
                  ) : (
                    item[c]
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {total > items.length && (
        <p className="mt-1 text-xs text-neutral-500">
          Showing {items.length} of {total}.
        </p>
      )}
    </div>
  );
}
