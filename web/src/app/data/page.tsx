import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import { getJson, type DataStatus, type QualitySummary } from "@/lib/api";

export const dynamic = "force-dynamic";

const sourceNames: Record<string, string> = {
  nse_bhavcopy: "NSE prices (bhavcopy)",
  nse_pr: "NSE corporate actions",
  yahoo: "Second source (Yahoo)",
};

export default async function DataPage() {
  const [status, reports] = await Promise.all([
    getJson<DataStatus>("/data/status"),
    getJson<QualitySummary[]>("/data/quality?limit=120"),
  ]);

  if (!status.ok) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Data quality</h1>
        <p className="mt-4 text-bad">{status.error}</p>
      </main>
    );
  }
  const s = status.data;
  const latest = s.latest_quality;

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Data quality</h1>

      <section
        className={`mt-6 rounded-lg border px-4 py-3 ${
          s.scan_allowed
            ? "border-line"
            : "border-bad/40"
        }`}
      >
        {latest ? (
          <>
            <div className="flex items-center gap-3">
              <StatusBadge status={latest.status} />
              <span>
                Latest trading day{" "}
                <Link className="underline" href={`/data/quality/${latest.trade_date}`}>
                  {latest.trade_date}
                </Link>
                {s.scan_allowed ? ": the scan may run." : ": the scan will not run."}
              </span>
            </div>
            {latest.reasons.length > 0 && (
              <ul className="mt-2 list-disc pl-6 text-sm text-muted">
                {latest.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <p>
            No data yet. Run <code>python -m app.cli backfill</code>, then{" "}
            <code>python -m app.cli daily</code> (see the README).
          </p>
        )}
      </section>

      <h2 className="mt-8 text-lg font-semibold">What is stored</h2>
      <table className="mt-2 w-full text-sm">
        <thead className="text-left text-muted">
          <tr>
            <th className="py-1">Source</th>
            <th>From</th>
            <th>To</th>
            <th className="text-right">Days</th>
          </tr>
        </thead>
        <tbody>
          {s.coverage.map((c) => (
            <tr key={c.source} className="border-t border-line">
              <td className="py-1">{sourceNames[c.source] ?? c.source}</td>
              <td>{c.first_date ?? "-"}</td>
              <td>{c.last_date ?? "-"}</td>
              <td className="text-right">{c.days}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-sm text-muted">
        {s.instruments} stocks, {s.corporate_actions} corporate-action records.
      </p>

      <h2 className="mt-8 text-lg font-semibold">Daily reports</h2>
      {reports.ok ? (
        <table className="mt-2 w-full text-sm">
          <tbody>
            {reports.data.map((r) => (
              <tr key={r.trade_date} className="border-t border-line">
                <td className="py-1 pr-4 whitespace-nowrap">
                  <Link className="underline" href={`/data/quality/${r.trade_date}`}>
                    {r.trade_date}
                  </Link>
                </td>
                <td className="pr-4">
                  <StatusBadge status={r.status} />
                </td>
                <td className="text-muted">{r.reasons.join("; ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="mt-2 text-bad">{reports.error}</p>
      )}
    </main>
  );
}
