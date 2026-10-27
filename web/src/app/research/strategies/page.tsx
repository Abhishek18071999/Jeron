import Link from "next/link";

import { EvidenceBadge, HealthText, StrategyStatusBadge } from "@/components/strategy-status";
import { Card, Notice, Page, PageHeader, Table, Td, Th, cli, shortDate } from "@/components/ui";
import { type EvidenceRating, type StrategyRow, getJson } from "@/lib/api";

export const dynamic = "force-dynamic";

type RegistryRow = {
  key: string | null;
  version: string;
  name: string;
  tier: string | null;
  in_code: boolean;
  grid_points: number | null;
  registered_on: string | null;
  runs: number;
  variants_logged: number;
  latest_run_id: number | null;
  latest_run_date: string | null;
  live_eligible: boolean | null;
  evidence: EvidenceRating | null;
  expectancy_r: number | null;
  deflated_sharpe: number | null;
};

type Registry = { rows: RegistryRow[]; versions: number; grid_points: number; runs: number; passed: number; note: string };

// Every strategy version, with its status and evidence, and the registry of all
// versions tried (decision 0018): the number of tries behind a "best" result is never hidden.
export default async function StrategiesPage() {
  const [statusResult, registryResult] = await Promise.all([
    getJson<StrategyRow[]>("/strategies"),
    getJson<Registry>("/strategies/registry"),
  ]);
  return (
    <Page>
      <PageHeader
        title="Strategies and evidence"
        subtitle="Status, evidence strength and paper health for every strategy version, and everything ever tried."
      />
      {!statusResult.ok ? (
        <Notice tone="bad">{statusResult.error}</Notice>
      ) : (
        <Card
          title="Status"
          subtitle="Research and Paper are Jeron's; Small capital and Approved only ever yours, once the evidence allows"
        >
          <Table stack>
            <thead>
              <tr>
                <Th>Strategy</Th>
                <Th>Status</Th>
                <Th>Evidence</Th>
                <Th>Paper</Th>
                <Th>Why</Th>
              </tr>
            </thead>
            <tbody>
              {statusResult.data.map((s) => (
                <tr key={s.version}>
                  <Td label="Strategy">
                    {s.run_id ? (
                      <Link href={`/backtests/${s.run_id}`} className="font-medium hover:underline">
                        {s.version}
                      </Link>
                    ) : (
                      <span className="font-medium">{s.version}</span>
                    )}
                    <span className="block text-xs text-muted">{s.tier}</span>
                  </Td>
                  <Td label="Status">
                    <StrategyStatusBadge status={s.status.status} />
                    {s.status.since && <span className="block text-xs text-muted">since {shortDate(s.status.since)}</span>}
                  </Td>
                  <Td label="Evidence">
                    <EvidenceBadge rating={s.evidence?.rating} title={s.evidence?.summary} />
                  </Td>
                  <Td label="Paper">
                    <HealthText health={s.health} />
                    {s.health?.false_retirement != null && (
                      <span
                        className="block text-xs text-muted"
                        title="How often the weekly 50-trade rule would retire a strategy exactly as good as this backtest, within 200 trades"
                      >
                        rule retires a backtest-like run {Math.round(s.health.false_retirement * 100)}% of the time
                      </span>
                    )}
                  </Td>
                  <Td label="Why">
                    <span className="text-xs">{s.status.reason}</span>
                    {s.health && s.health.verdict !== "too early" && (
                      <span className="block text-xs text-muted">{s.health.detail}</span>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <p className="mt-3 text-xs text-muted">
            To change a status, with the reason kept beside it: <code>{cli('strategy-status rs-pullback-v1 "small capital" --reason "..."')}</code>.
            Jeron refuses when the paper gate or the evidence doesn&apos;t allow it, and a retired strategy needs a new
            passing backtest before it can paper-trade again.
          </p>
        </Card>
      )}
      {registryResult.ok && (
        <Card title="Everything tried" subtitle={registryResult.data.note}>
          <Table stack>
            <thead>
              <tr>
                <Th>Version</Th>
                <Th num>Parameter sets</Th>
                <Th num>Runs</Th>
                <Th>Latest run</Th>
                <Th num>Expectancy</Th>
                <Th num>Deflated Sharpe</Th>
                <Th>Evidence</Th>
              </tr>
            </thead>
            <tbody>
              {registryResult.data.rows.map((r) => (
                <tr key={r.version} className={r.in_code ? "" : "text-muted"}>
                  <Td label="Version">
                    {r.version}
                    {!r.in_code && <span className="block text-xs">no longer in the code</span>}
                  </Td>
                  <Td label="Parameter sets" num>
                    {r.grid_points ?? "-"}
                  </Td>
                  <Td label="Runs" num>
                    {r.runs}
                  </Td>
                  <Td label="Latest run">
                    {r.latest_run_id ? (
                      <Link href={`/backtests/${r.latest_run_id}`} className="hover:underline">
                        {shortDate(r.latest_run_date)} {r.live_eligible ? "· passed" : "· failed"}
                      </Link>
                    ) : (
                      "never run"
                    )}
                  </Td>
                  <Td label="Expectancy" num>
                    {r.expectancy_r == null ? "-" : `${r.expectancy_r.toFixed(3)}R`}
                  </Td>
                  <Td label="Deflated Sharpe" num>
                    {r.deflated_sharpe == null ? "-" : r.deflated_sharpe.toFixed(2)}
                  </Td>
                  <Td label="Evidence">{r.latest_run_id ? <EvidenceBadge rating={r.evidence} /> : "-"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </Page>
  );
}
