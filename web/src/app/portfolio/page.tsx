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
  inr,
  inrSigned,
  pctText,
  rMultiple,
  shortDate,
  signTone,
  RunCommand,
} from "@/components/ui";
import { type AccountGuardrails, type EquityCurve, type Portfolio, getJson } from "@/lib/api";

export const dynamic = "force-dynamic";

// `?day=YYYY-MM-DD` shows the exit plans as that session's pre-open check saw them.
export default async function PortfolioPage({ searchParams }: { searchParams: Promise<{ day?: string }> }) {
  const { day } = await searchParams;
  const dayParam = day && /^\d{4}-\d{2}-\d{2}$/.test(day) ? `?day=${day}` : "";
  const [result, equity] = await Promise.all([
    getJson<Portfolio>(`/portfolio${dayParam}`),
    getJson<EquityCurve>("/portfolio/equity"),
  ]);
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
          below use older closes. <RunCommand job="daily" />
        </Notice>
      )}
      {t.warnings.map((w) => (
        <Notice key={w} tone="warn">
          {w}
        </Notice>
      ))}
      {t.cash_action && <Notice>{t.cash_action}</Notice>}
      {t.tax_notes.map((n) => (
        <Notice key={n}>{n}</Notice>
      ))}
      {t.exemption && <Notice>{t.exemption.line}</Notice>}
      {p.account && <Guardrails a={p.account} />}
      {equity.ok && equity.data.points.length > 1 && <EquityCard c={equity.data} />}

      {t.positions === 0 ? (
        <Card>
          <EmptyState>
            Positions come from the journal: record a fill on a signal, add a trade you took without one, or
            upload your Zerodha tradebook on the Journal page.
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
                how="For each open position: what you sold for plus the shares still held at the last close, minus what you paid and every charge in the journal. Added up over the positions."
              />
              <Stat
                label="Open risk"
                value={inr(t.open_risk, 0)}
                tone={heat >= Number(t.heat_warn_pct) ? "warn" : "neutral"}
                sub={`${pctText(heat, 1)} of capital`}
                help="Entry minus today's stop, times shares, summed. A stop at breakeven or above adds nothing."
                how={`Shown as a share of your capital (${inr(t.capital, 0)}): that share is the portfolio heat. Above ${pctText(t.heat_warn_pct, 0)} Jeron warns; at ${pctText(t.heat_block_pct, 0)} a new trade plan is blocked.`}
              />
              <Stat
                label="If every stop is hit"
                value={inrSigned(-Number(t.give_back))}
                help="What you would give back from today's close if every position hit its current stop."
                how="For each position: (last close minus its current stop) times the shares held, added up. It is the worst case if every stop fills exactly; a gap down can cost more. It is not a loss you have now."
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
              <Table stack>
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
                      <Td label="Stock">
                        <Link href={`/journal/${h.entry_id}`} className="font-semibold hover:underline">
                          {h.ticker}
                        </Link>
                        <span className="block text-xs text-muted">{h.sector ?? "sector unknown"}</span>
                      </Td>
                      <Td label="Qty" num>{h.shares}</Td>
                      <Td label="Avg price" num>{inr(h.avg_entry)}</Td>
                      <Td label="Last close" num>{inr(h.last_close)}</Td>
                      <Td label="P&L" num className={signTone(h.pnl)}>
                        {inrSigned(h.pnl)}
                      </Td>
                      <Td label="R" num className={signTone(h.r_multiple)}>
                        {rMultiple(h.r_multiple)}
                      </Td>
                      <Td label="To stop" num title={h.stop ? `Stop ${inr(h.stop)}` : "No stop"}>
                        {h.stop_distance_pct === null ? "-" : pctText(h.stop_distance_pct, 1)}
                        <span className="block text-xs text-muted">{h.stop ? inr(h.stop) : "no stop"}</span>
                      </Td>
                      <Td label="Held"
                        num
                        title={
                          h.sessions_held === null ? undefined : `${h.sessions_held} sessions after the entry day`
                        }
                      >
                        {h.days_held}d
                      </Td>
                      <Td label="Exit plan" className="max-w-[18rem]">
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
                    <Td label="Stock">
                      Total
                      <span className="block text-xs font-normal text-muted">value {inr(t.value, 0)}</span>
                    </Td>
                    <Td num />
                    <Td num />
                    <Td num />
                    <Td label="P&L" num className={signTone(t.pnl)}>
                      {inrSigned(t.pnl)}
                    </Td>
                    <Td num />
                    <Td label="To stop" num className="font-normal text-muted">
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

// The limits a new trade plan is checked against (spec section 5 and the Settings page).
function Guardrails({ a }: { a: AccountGuardrails }) {
  const loss = (realised: string, limit: string | null) => {
    const lost = Math.max(0, -Number(realised));
    return {
      value: <span className={signTone(realised)}>{inrSigned(realised)}</span>,
      sub: limit ? `limit: a loss of ${inr(limit, 0)}` : "no limit set",
      tone: (limit && lost >= Number(limit) ? "bad" : "neutral") as "bad" | "neutral",
      hit: Boolean(limit && lost >= Number(limit)),
    };
  };
  const stops = a.limits_block ? "new trade plans are blocked" : "new trade plans get a warning";
  const today = loss(a.realised_today, a.daily_loss_limit);
  const week = loss(a.realised_week, a.weekly_loss_limit);
  const capped = a.max_entries_week !== null && a.entries_week >= a.max_entries_week;
  return (
    <>
      {a.brake === "paused" && (
        <Notice tone="bad">
          The account is {pctText(a.drawdown_pct, 1)} below its peak of {inr(a.peak, 0)}: new trade plans are
          blocked until it recovers above {pctText(a.drawdown_pause_pct, 0)}. Review the recent trades in the
          journal before the next one.
        </Notice>
      )}
      {a.brake === "halved" && (
        <Notice tone="warn">
          The account is {pctText(a.drawdown_pct, 1)} below its peak: new trade plans risk half the usual amount
          until it is back within {pctText(a.drawdown_halve_pct, 0)}.
        </Notice>
      )}
      {today.hit && (
        <Notice tone={a.limits_block ? "bad" : "warn"}>
          Today&apos;s realised losses ({inr(-Number(a.realised_today), 0)}) reached the daily limit of{" "}
          {inr(a.daily_loss_limit, 0)}: {stops} until tomorrow.
        </Notice>
      )}
      {week.hit && (
        <Notice tone={a.limits_block ? "bad" : "warn"}>
          This week&apos;s realised losses ({inr(-Number(a.realised_week), 0)}) reached the weekly limit of{" "}
          {inr(a.weekly_loss_limit, 0)}: {stops} until Monday.
        </Notice>
      )}
      {capped && (
        <Notice tone={a.limits_block ? "bad" : "warn"}>
          {a.entries_week} new positions this week, the cap set on Settings: {stops} until Monday.
        </Notice>
      )}
      <Card title="Guardrails">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat
            label="Below the peak"
            value={pctText(a.drawdown_pct, 1)}
            tone={a.brake === "paused" ? "bad" : a.brake === "halved" ? "warn" : "neutral"}
            sub={`equity ${inr(a.equity, 0)}, peak ${inr(a.peak, 0)}`}
            help={`At ${pctText(a.drawdown_halve_pct, 0)} below the peak the risk per trade is halved; at ${pctText(a.drawdown_pause_pct, 0)} new entries stop (spec section 5).`}
            how="Equity is your capital setting plus every realised gain or loss in the journal plus the open positions at the last close. The peak is the highest equity on any session since your first buy, open positions marked at each day's close (the equity chart below)."
          />
          <Stat
            label="Realised today"
            value={today.value}
            tone={today.tone}
            sub={today.sub}
            help="Gains and losses of today's sales in the journal, after charges. At the daily loss limit a new plan is blocked (or warned, per Settings)."
          />
          <Stat
            label="Realised this week"
            value={week.value}
            tone={week.tone}
            sub={week.sub}
            help="Sales from Monday on, after charges, against the weekly loss limit."
          />
          <Stat
            label="New positions this week"
            value={a.max_entries_week === null ? String(a.entries_week) : `${a.entries_week} of ${a.max_entries_week}`}
            tone={capped ? "warn" : "neutral"}
            sub={a.limits_block ? "limits block a plan" : "limits only warn"}
            help="Journal positions first bought from Monday on, against the weekly cap set on Settings (against overtrading)."
          />
        </div>
      </Card>
    </>
  );
}

function EquityCard({ c }: { c: EquityCurve }) {
  const W = 600;
  const H = 140;
  const eq = c.points.map((p) => Number(p.equity));
  const ix = c.points.map((p) => (p.index === null ? null : Number(p.index)));
  const all = [...eq, ...ix.filter((v): v is number => v !== null)];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 1;
  const x = (i: number) => ((i / (c.points.length - 1)) * W).toFixed(1);
  const y = (v: number) => (H - ((v - lo) / span) * (H - 8) - 4).toFixed(1);
  const path = (values: (number | null)[]) => {
    let d = "";
    let pen = false;
    values.forEach((v, i) => {
      if (v === null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(i)},${y(v)} `;
      pen = true;
    });
    return d.trim();
  };
  const first = c.points[0];
  const last = c.points[c.points.length - 1];
  return (
    <Card
      title="Account equity"
      subtitle={`${shortDate(first.day)} to ${shortDate(last.day)} · solid: your account, dashed: the same capital in the Nifty 500`}
    >
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Your return" value={pctText(c.return_pct, 2, true)} tone={Number(c.return_pct) > 0 ? "good" : Number(c.return_pct) < 0 ? "bad" : "neutral"} />
        <Stat label="Nifty 500 (price)" value={c.index_return_pct === null ? "n/a" : pctText(c.index_return_pct, 2, true)} />
        <Stat label="Worst drawdown" value={pctText(c.max_drawdown_pct, 2)} sub={c.peak ? `peak ${inr(c.peak, 0)}` : undefined} />
        <Stat label="Equity now" value={inr(last.equity, 0)} sub={`capital ${inr(c.capital, 0)}`} />
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="mt-3 h-36 w-full"
        role="img"
        aria-label="Account equity against the Nifty 500"
      >
        <path d={path(ix)} fill="none" className="stroke-muted" strokeWidth={1.2} strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
        <path d={path(eq)} fill="none" className="stroke-accent" strokeWidth={1.8} vectorEffect="non-scaling-stroke" />
      </svg>
      <p className="mt-2 text-xs text-muted">{c.note}</p>
    </Card>
  );
}
