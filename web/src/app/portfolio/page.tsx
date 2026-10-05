import Link from "next/link";

import { ActionBadge, HeatMeter, HoldingCard, SectorBars } from "@/components/portfolio";
import {
  Card,
  EmptyState,
  LinkButton,
  Notice,
  Page,
  PageHeader,
  Stat,
  Table,
  Td,
  Th,
  cli,
  inr,
  inrSigned,
  pctText,
  rMultiple,
  shortDate,
  signTone,
} from "@/components/ui";
import { type Portfolio, getJson } from "@/lib/api";

export const dynamic = "force-dynamic";

// `?day=YYYY-MM-DD` shows the exit plans as that session's pre-open check saw them.
export default async function PortfolioPage({ searchParams }: { searchParams: Promise<{ day?: string }> }) {
  const { day } = await searchParams;
  const dayParam = day && /^\d{4}-\d{2}-\d{2}$/.test(day) ? `?day=${day}` : "";
  const result = await getJson<Portfolio>(`/portfolio${dayParam}`);
  if (!result.ok) {
    return (
      <Page>
        <PageHeader title="Portfolio" />
        <Notice tone="bad">{result.error}</Notice>
      </Page>
    );
  }
  const p = result.data;
  const t = p.totals;
  const holdings = [...p.holdings].sort((a, b) => Number(b.value ?? 0) - Number(a.value ?? 0));
  const heat = Number(t.heat_pct);

  return (
    <Page>
      <PageHeader
        title="Portfolio"
        subtitle={
          t.positions === 0 ? (
            "No open positions in the journal"
          ) : (
            <>
              <span className="font-medium text-fg">
                {t.positions} open position{t.positions > 1 ? "s" : ""} worth {inr(t.value, 0)},{" "}
                <span className={signTone(t.pnl)}>{inrSigned(t.pnl)}</span>
              </span>
              {p.data_as_of && <span> · closes to {shortDate(p.data_as_of)}</span>}
            </>
          )
        }
        action={
          <LinkButton href="/journal" variant="secondary">
            Journal
          </LinkButton>
        }
      />

      {p.stale && t.positions > 0 && (
        <Notice tone="warn">
          Prices for {shortDate(p.expected)} are not loaded (latest: {shortDate(p.data_as_of)}). Exit actions
          below use older closes. Run <code>{cli("daily")}</code>
        </Notice>
      )}
      {t.warnings.map((w) => (
        <Notice key={w} tone="warn">
          {w}
        </Notice>
      ))}

      {t.positions === 0 ? (
        <Card>
          <EmptyState command={cli("tradebook FILE")}>
            Positions come from the journal: record a fill on a signal, add a trade you took without one, or
            import your Zerodha tradebook (Journal page, or the command below with the CSV).
          </EmptyState>
        </Card>
      ) : (
        <>
          <Card>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Stat label="Market value" value={inr(t.value, 0)} sub={`capital ${inr(t.capital, 0)}`} />
              <Stat
                label="P&L"
                value={<span className={signTone(t.pnl)}>{inrSigned(t.pnl)}</span>}
                help="Realised and open profit or loss of the open positions, after charges."
              />
              <Stat
                label="Open risk"
                value={inr(t.open_risk, 0)}
                tone={heat >= Number(t.heat_warn_pct) ? "warn" : "neutral"}
                sub={`${pctText(heat, 1)} of capital`}
                help="Entry minus today's stop, times shares, summed. A stop at breakeven or above adds nothing."
              />
              <Stat
                label="If every stop is hit"
                value={inrSigned(-Number(t.give_back))}
                help="What you would give back from today's close if every position hit its current stop."
                sub={t.without_stop ? `${t.without_stop} without a stop` : "all positions have a stop"}
              />
            </div>
            <div className="mt-4">
              <HeatMeter totals={t} />
            </div>
          </Card>

          <Card title="Open positions" subtitle="Exit plans by the engine's rules, as the pre-open check sees them">
            <ul className="md:hidden">
              {holdings.map((h) => (
                <HoldingCard key={h.entry_id} h={h} />
              ))}
            </ul>
            <div className="hidden md:block">
              <Table>
                <thead>
                  <tr>
                    <Th>Stock</Th>
                    <Th num>Qty</Th>
                    <Th num>Avg price</Th>
                    <Th num>Last close</Th>
                    <Th num help="Realised and open, after charges">
                      P&amp;L
                    </Th>
                    <Th num help="P&L in units of the initial risk (entry minus initial stop)">
                      R
                    </Th>
                    <Th num help="How far the last close is above today's stop">
                      To stop
                    </Th>
                    <Th num help="Calendar days since the first buy">
                      Held
                    </Th>
                    <Th>Exit plan</Th>
                  </tr>
                </thead>
                <tbody>
                  {holdings.map((h) => (
                    <tr key={h.entry_id}>
                      <Td>
                        <Link href={`/journal/${h.entry_id}`} className="font-semibold hover:underline">
                          {h.ticker}
                        </Link>
                        <span className="block text-xs text-muted">{h.sector ?? "sector unknown"}</span>
                      </Td>
                      <Td num>{h.shares}</Td>
                      <Td num>{inr(h.avg_entry)}</Td>
                      <Td num>{inr(h.last_close)}</Td>
                      <Td num className={signTone(h.pnl)}>
                        {inrSigned(h.pnl)}
                      </Td>
                      <Td num className={signTone(h.r_multiple)}>
                        {rMultiple(h.r_multiple)}
                      </Td>
                      <Td num title={h.stop ? `Stop ${inr(h.stop)}` : "No stop"}>
                        {h.stop_distance_pct === null ? "-" : pctText(h.stop_distance_pct, 1)}
                        <span className="block text-xs text-muted">{h.stop ? inr(h.stop) : "no stop"}</span>
                      </Td>
                      <Td
                        num
                        title={
                          h.sessions_held === null ? undefined : `${h.sessions_held} sessions after the entry day`
                        }
                      >
                        {h.days_held}d
                      </Td>
                      <Td className="max-w-[18rem]">
                        <ActionBadge h={h} />
                        <span className="mt-0.5 block text-xs text-muted">{h.problem ?? h.reason}</span>
                        {h.events.map((e) => (
                          <span key={e} className="mt-0.5 block text-xs text-warn">
                            {e}
                          </span>
                        ))}
                      </Td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="font-semibold">
                    <Td>
                      Total
                      <span className="block text-xs font-normal text-muted">value {inr(t.value, 0)}</span>
                    </Td>
                    <Td num />
                    <Td num />
                    <Td num />
                    <Td num className={signTone(t.pnl)}>
                      {inrSigned(t.pnl)}
                    </Td>
                    <Td num />
                    <Td num className="font-normal text-muted">
                      {inr(t.open_risk, 0)} at risk
                    </Td>
                    <Td num />
                    <Td />
                  </tr>
                </tfoot>
              </Table>
            </div>
          </Card>

          <Card
            title="Sector exposure"
            subtitle={`Market value per NSE industry as a share of capital; the line marks the ${pctText(t.sector_cap_pct, 0)} cap`}
          >
            <SectorBars totals={t} />
          </Card>
        </>
      )}
    </Page>
  );
}
