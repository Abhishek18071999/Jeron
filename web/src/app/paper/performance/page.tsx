import Link from "next/link";

import {
  Badge,
  Card,
  EmptyState,
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
import {
  getJson,
  type AuditEvent,
  type PaperAccount,
  type PaperReview,
  type PaperReviewView,
  type ReviewTrade,
} from "@/lib/api";
import { TOP_SCORE_KEY, missedRows, pickAccount, proposalNext, proposalTone, versusBenchmark } from "@/lib/paper-review";

import { EquityLine, StageBadge } from "../parts";

export const dynamic = "force-dynamic";

const num = (v: number | null | undefined, digits = 2) => (v === null || v === undefined ? "-" : v.toFixed(digits));
const pct = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? "-" : `${(v * 100).toFixed(digits)}%`);
const range = (r: [number, number] | null | undefined) => (r ? `${rMultiple(r[0])} to ${rMultiple(r[1])}` : "-");

export default async function PaperPerformance({ searchParams }: { searchParams: Promise<{ account?: string }> }) {
  const sp = await searchParams;
  const accounts = await getJson<PaperAccount[]>("/paper/accounts");
  const header = (
    <PageHeader
      title="Paper performance"
      subtitle="Simulated trading of each strategy by its plan, reviewed: what worked, what failed, why, and which changes are worth testing."
    />
  );
  if (!accounts.ok || accounts.data.length === 0) {
    return (
      <Page>
        {header}
        <EmptyState command={cli("paper")}>
          {accounts.ok ? "No paper accounts yet. They open after each strategy's backtest, on the day of the next scan." : accounts.error}
        </EmptyState>
      </Page>
    );
  }
  const account = pickAccount(accounts.data, sp.account)!;
  const [view, audit] = await Promise.all([
    getJson<PaperReviewView>(`/paper/accounts/${account.id}/review`),
    getJson<AuditEvent[]>(`/paper/accounts/${account.id}/audit?limit=40`),
  ]);
  const hasTopScore = accounts.data.some((a) => a.strategy_key === TOP_SCORE_KEY);

  return (
    <Page>
      {header}
      <nav className="flex flex-wrap gap-2 text-sm" aria-label="Paper accounts">
        {accounts.data.map((a) => (
          <Link
            key={a.id}
            href={`/paper/performance?account=${a.id}`}
            className={`rounded-full border px-3 py-1 ${a.id === account.id ? "border-accent bg-accent-bg text-accent" : "border-line hover:bg-surface-2"}`}
          >
            {a.strategy_key === TOP_SCORE_KEY ? "90+ score" : a.strategy_name}
          </Link>
        ))}
      </nav>
      {!hasTopScore && (
        <Notice tone="warn">
          The 90+ score account (<code>top-score-v1</code>) opens after its backtest, which the autopilot runs by itself;
          then the daily run paper-trades it from the next scan. No trades are made up to fill it.
        </Notice>
      )}
      {!view.ok ? <Notice tone="bad">{view.error}</Notice> : <Review view={view.data} audit={audit.ok ? audit.data : []} />}
    </Page>
  );
}

function Review({ view, audit }: { view: PaperReviewView; audit: AuditEvent[] }) {
  const { account: a, days, review: r } = view;
  return (
    <>
      <Notice tone="warn">
        <strong>Simulated, not real money.</strong> {a.strategy_name} ({a.strategy_version}, {a.params_label}) on paper since{" "}
        {shortDate(a.start_date)}, updated to {shortDate(a.last_date)}, from end-of-day data only.{" "}
        {a.stage === "paper"
          ? "It passed its backtest, so its signals are alerts."
          : "It has not passed its backtest, so its signals are research only, never alerts."}{" "}
        Your real results are on <Link href="/portfolio" className="underline">Portfolio</Link> and{" "}
        <Link href="/journal" className="underline">Journal</Link>. <StageBadge stage={a.stage} />
      </Notice>
      <JournalCard r={r} />
      <PerformanceCard r={r} days={days} capital={Number(a.capital)} />
      <PlanCard r={r} />
      <RootCauseCard r={r} />
      <OptimisationCard r={r} />
      <ValidationCard r={r} />
      <AuditCard audit={audit} total={r.audit_events} />
      <Card title="Data limitations">
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {r.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </Card>
    </>
  );
}

function Why({ t }: { t: ReviewTrade }) {
  if (!t.why.length && !t.exit_reason) return <span className="text-muted">-</span>;
  return (
    <details>
      <summary className="cursor-pointer text-muted">Why</summary>
      <ul className="mt-1 list-disc pl-4 text-xs">
        {t.why.map((w) => (
          <li key={w}>{w}</li>
        ))}
        {t.exit_reason && <li>Sold: {t.exit_reason}</li>}
      </ul>
    </details>
  );
}

function JournalCard({ r }: { r: PaperReview }) {
  const { open, closed, allocation } = r.journal;
  return (
    <Card title="Live trade journal" subtitle="Every paper trade as the rules made it, with prices, charges and the reasons.">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Equity" value={inr(allocation.equity, 0)} />
        <Stat label="In stocks" value={inr(allocation.invested, 0)} sub={`${open.length} open positions`} />
        <Stat label="Cash" value={inr(allocation.cash, 0)} sub={pctText(allocation.cash_pct)} />
        <Stat label="Closed trades" value={String(closed.length)} />
      </div>
      <h3 className="mt-5 text-sm font-semibold">Open positions</h3>
      {open.length === 0 ? (
        <p className="mt-1 text-sm text-muted">None.</p>
      ) : (
        <Table stack>
          <thead>
            <tr>
              <Th>Stock</Th>
              <Th>Entry</Th>
              <Th num>Price</Th>
              <Th num>Stop now</Th>
              <Th num>Close</Th>
              <Th num>Shares</Th>
              <Th num help="Share of the account's equity in this position at the last close.">Of equity</Th>
              <Th num>P&amp;L</Th>
              <Th num>R</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {open.map((t) => (
              <tr key={t.seq}>
                <Td label="Stock" className="font-medium">
                  <Link href={`/stocks/${t.ticker}`} className="underline">
                    {t.ticker}
                  </Link>
                  <div className="text-xs text-muted">{t.sector ?? "no sector"}</div>
                </Td>
                <Td label="Entry">{shortDate(t.entry_date)}</Td>
                <Td label="Price" num>{inr(t.entry_price)}</Td>
                <Td label="Stop now" num>{inr(t.current_stop)}</Td>
                <Td label="Close" num>{inr(t.last_close)}</Td>
                <Td label="Shares" num>{t.shares_held}</Td>
                <Td label="Of equity" num>{pctText(t.pct_of_equity)}</Td>
                <Td label="P&L" num className={signTone(t.net_pnl)}>{inrSigned(t.net_pnl)}</Td>
                <Td label="R" num className={signTone(t.r)}>{rMultiple(t.r)}</Td>
                <Td label="Why"><Why t={t} /></Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {allocation.sectors.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          By sector: {allocation.sectors.map((s) => `${s.sector} ${pctText(s.pct_of_equity)}`).join(", ")}.
        </p>
      )}
      <h3 className="mt-5 text-sm font-semibold">Closed trades</h3>
      {closed.length === 0 ? (
        <p className="mt-1 text-sm text-muted">None yet.</p>
      ) : (
        <Table stack>
          <thead>
            <tr>
              <Th>Stock</Th>
              <Th>Bought</Th>
              <Th num>Price</Th>
              <Th>Sold</Th>
              <Th num>Price</Th>
              <Th num>Charges</Th>
              <Th num>P&amp;L</Th>
              <Th num>R</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {closed.slice(0, 20).map((t) => (
              <tr key={t.seq}>
                <Td label="Stock" className="font-medium">
                  {t.ticker}
                  <div className="text-xs text-muted">score {num(t.score, 0)}</div>
                </Td>
                <Td label="Bought">{shortDate(t.entry_date)}</Td>
                <Td label="Price" num>{inr(t.entry_price)}</Td>
                <Td label="Sold">{shortDate(t.exit_date)}</Td>
                <Td label="Price" num>{inr(t.exit_price)}</Td>
                <Td label="Charges" num>{inr(t.charges, 0)}</Td>
                <Td label="P&L" num className={signTone(t.net_pnl)}>{inrSigned(t.net_pnl)}</Td>
                <Td label="R" num className={signTone(t.r)}>{rMultiple(t.r)}</Td>
                <Td label="Why"><Why t={t} /></Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {closed.length > 20 && (
        <p className="mt-2 text-xs text-muted">
          The newest 20 of {closed.length}; every trade is in the audit trail and on the{" "}
          <Link href="/paper" className="underline">paper account&apos;s page</Link>.
        </p>
      )}
    </Card>
  );
}

function PerformanceCard({ r, days, capital }: { r: PaperReview; days: PaperReviewView["days"]; capital: number }) {
  const p = r.performance;
  const t = p.trades;
  const bt = p.backtest;
  return (
    <Card title="Performance" subtitle={`Paper, after charges and slippage. Sharpe and Sortino count returns above the ${p.cash_rate_pct ?? 6.5}% cash rate.`}>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Return" value={versusBenchmark(p.curve?.total_return, p.benchmark?.total_return)} tone={p.excess_return && p.excess_return > 0 ? "good" : p.excess_return && p.excess_return < 0 ? "bad" : "neutral"} />
        <Stat label="Win rate" value={pct(t.win_rate)} sub={`${t.wins} of ${t.trades} closed`} />
        <Stat
          label="Reward:risk (realised)"
          value={num(t.payoff_ratio)}
          sub={`wins ${rMultiple(t.avg_win_r)}, losses ${rMultiple(t.avg_loss_r)}`}
          help="The average winning trade's R over the average losing trade's."
        />
        <Stat label="Expectancy" value={rMultiple(t.expectancy_r)} sub={`95% range ${range(t.expectancy_interval)}`} tone={t.expectancy_r && t.expectancy_r > 0 ? "good" : "neutral"} />
        <Stat label="Profit factor" value={num(t.profit_factor)} />
        <Stat label="Max drawdown" value={pctText(p.curve?.max_drawdown_pct)} sub={`Nifty 500 ${pctText(p.benchmark?.max_drawdown_pct)}`} />
        <Stat label="Sharpe / Sortino" value={`${num(p.curve?.sharpe)} / ${num(p.profile?.sortino)}`} sub={`Nifty 500 Sharpe ${num(p.benchmark?.sharpe)}`} />
        <Stat label="Charges" value={inr(t.charges, 0)} sub={t.charges_pct_of_gains !== null ? `${num(t.charges_pct_of_gains, 0)}% of the winners' profit` : undefined} />
      </div>
      {t.sample_note && <Notice tone="warn">{t.sample_note}</Notice>}
      <div className="mt-4">
        <EquityLine days={days} capital={capital} />
      </div>
      {bt && (
        <>
          <h3 className="mt-4 text-sm font-semibold">Against its backtest</h3>
          <Table>
            <thead>
              <tr>
                <Th />
                <Th num>Trades</Th>
                <Th num>Win rate</Th>
                <Th num>Expectancy</Th>
                <Th num>Profit factor</Th>
                <Th num>Max drawdown</Th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <Td>Paper</Td>
                <Td num>{t.trades}</Td>
                <Td num>{pct(t.win_rate)}</Td>
                <Td num>{rMultiple(t.expectancy_r)}</Td>
                <Td num>{num(t.profit_factor)}</Td>
                <Td num>{pctText(p.curve?.max_drawdown_pct)}</Td>
              </tr>
              <tr>
                <Td>Backtest (out of sample)</Td>
                <Td num>{bt.trades?.trades ?? "-"}</Td>
                <Td num>{pct(bt.trades?.win_rate)}</Td>
                <Td num>{rMultiple(bt.trades?.expectancy_r)}</Td>
                <Td num>{bt.trades ? String(typeof bt.trades.profit_factor === "number" ? bt.trades.profit_factor.toFixed(2) : bt.trades.profit_factor) : "-"}</Td>
                <Td num>{pctText(bt.max_drawdown_pct)}</Td>
              </tr>
            </tbody>
          </Table>
          <p className="mt-2 text-xs text-muted">
            Whether the difference is ordinary variance is on <Link href="/compare" className="underline">Backtest vs paper vs real</Link>.
          </p>
        </>
      )}
    </Card>
  );
}

function PlanCard({ r }: { r: PaperReview }) {
  const plan = r.plan;
  const missed = plan.missed ? missedRows(plan.missed) : [];
  return (
    <Card title="Plan evaluation" subtitle="What worked, what failed, signals the rules skipped, and where the record parted from the plan.">
      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold">How trades ended</h3>
          {plan.exits.length === 0 ? (
            <p className="mt-1 text-sm text-muted">No closed trades yet.</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Exit</Th>
                  <Th num>Trades</Th>
                  <Th num>Average</Th>
                  <Th num>P&amp;L</Th>
                </tr>
              </thead>
              <tbody>
                {plan.exits.map((e) => (
                  <tr key={e.exit}>
                    <Td>{e.exit}</Td>
                    <Td num>{e.trades}</Td>
                    <Td num className={signTone(e.avg_r)}>{rMultiple(e.avg_r)}</Td>
                    <Td num className={signTone(e.net_pnl)}>{inrSigned(e.net_pnl)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          <ul className="mt-3 space-y-1 text-sm">
            <li>
              <strong>Worked:</strong>{" "}
              {plan.best.length ? plan.best.map((t) => `${t.ticker} ${rMultiple(t.r)}`).join(", ") : "nothing yet"}
            </li>
            <li>
              <strong>Failed:</strong>{" "}
              {plan.worst.length ? plan.worst.map((t) => `${t.ticker} ${rMultiple(t.r)}`).join(", ") : "nothing yet"}
            </li>
            <li>
              <strong>False signals</strong> ({plan.false_signals.rule}): {plan.false_signals.trades}
              {plan.false_signals.share !== null ? ` (${pct(plan.false_signals.share, 0)} of closed)` : ""}
              {plan.false_signals.tickers.length ? `, latest ${plan.false_signals.tickers.join(", ")}` : ""}
            </li>
            <li>
              <strong>Through the stop</strong> ({plan.gap_through.rule}): {plan.gap_through.trades}
            </li>
          </ul>
        </div>
        <div>
          <h3 className="text-sm font-semibold">Missed opportunities</h3>
          {!plan.missed ? (
            <p className="mt-1 text-sm text-muted">Measured from the next update.</p>
          ) : (
            <>
              <p className="mt-1 text-xs text-muted">
                Each signal&apos;s move over the next {plan.missed.forward_sessions} sessions, from its signal close, in R (a 2 x ATR stop = 1R).
              </p>
              <Table>
                <thead>
                  <tr>
                    <Th>Signals</Th>
                    <Th num>Count</Th>
                    <Th num>Average move</Th>
                    <Th num help="The skipped signals' average move minus the traded ones'. Positive: the skipped ones did better.">vs traded</Th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <Td className="font-medium">Traded</Td>
                    <Td num>{plan.missed.taken.count}</Td>
                    <Td num>{rMultiple(plan.missed.taken.avg_move_r)}</Td>
                    <Td num />
                  </tr>
                  {missed.map((m) => (
                    <tr key={m.reason}>
                      <Td>Skipped: {m.reason}</Td>
                      <Td num>{m.line.count}</Td>
                      <Td num>{rMultiple(m.line.avg_move_r)}</Td>
                      <Td num className={signTone(m.versusTaken)}>{rMultiple(m.versusTaken)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </>
          )}
          <h3 className="mt-4 text-sm font-semibold">Deviations from the plan</h3>
          <p className="mt-1 text-xs text-muted">{plan.deviations.note}</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            <li>{plan.deviations.late_signals} signals recorded late (the paper job was catching up).</li>
            {plan.deviations.replay_changes.map((n) => (
              <li key={n}>{n}</li>
            ))}
            {plan.deviations.rejected_signals.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}

function RootCauseCard({ r }: { r: PaperReview }) {
  const rc = r.root_causes;
  return (
    <Card title="Root causes" subtitle="Closed trades grouped by what was known at each signal close, worst average first.">
      {rc.dimensions.length === 0 ? (
        <p className="text-sm text-muted">No closed trades with their signal context yet.</p>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          {rc.dimensions.map((d) => (
            <div key={d.dimension}>
              <h3 className="text-sm font-semibold">{d.groups[0]?.label}</h3>
              <Table>
                <thead>
                  <tr>
                    <Th>Group</Th>
                    <Th num>Trades</Th>
                    <Th num>Win rate</Th>
                    <Th num>Average</Th>
                    <Th num help="The 95% range of the average R. Wide ranges mean too few trades to tell.">95% range</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.groups.map((g) => (
                    <tr key={g.value}>
                      <Td>{g.value}</Td>
                      <Td num>{g.trades}</Td>
                      <Td num>{pct(g.win_rate, 0)}</Td>
                      <Td num className={signTone(g.avg_r)}>{rMultiple(g.avg_r)}</Td>
                      <Td num className="text-xs">{range(g.interval)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              {d.loss_concentration.share !== null && (
                <p className="mt-1 text-xs text-muted">
                  {pct(d.loss_concentration.share, 0)} of all the R lost came from {d.loss_concentration.value}.
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      {rc.big_losses.length > 0 && (
        <>
          <h3 className="mt-5 text-sm font-semibold">Losses of a full R or more</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {rc.big_losses.map((l) => (
              <li key={`${l.ticker}-${l.entry_date}`}>
                <span className="font-medium">{l.ticker}</span> {shortDate(l.entry_date)}{" "}
                <span className="text-bad">{rMultiple(l.r)}</span>: {l.exit_reason}; market {String(l.context.regime ?? "-")}
                {l.context.risk_off ? ", regime filter on" : ""}, score {num(l.context.score as number | null, 0)}, RSI{" "}
                {num(l.context.rsi as number | null, 0)}
              </li>
            ))}
          </ul>
        </>
      )}
      {rc.no_context > 0 && <p className="mt-2 text-xs text-muted">{rc.no_context} trades have no signal context yet (recorded before the next update).</p>}
    </Card>
  );
}

function OptimisationCard({ r }: { r: PaperReview }) {
  return (
    <Card
      title="Strategy optimisation"
      subtitle="Proposals come from a fixed rule, never from hand-picking, and are never applied by themselves."
    >
      <p className="text-sm">
        The rule: a group of at least 20 closed trades whose average R&apos;s 95% range is entirely below zero, while the
        other trades average above zero, becomes &quot;skip entries where &lt;group&gt;&quot;. Each proposal is stored once with its
        evidence and the time it was made.
      </p>
      {r.observations.length > 0 && (
        <>
          <h3 className="mt-4 text-sm font-semibold">Observations on exits, sizing and risk</h3>
          <p className="text-xs text-muted">These change the engine&apos;s rules, so each would be a new strategy version written and backtested by hand.</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {r.observations.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </>
      )}
      <h3 className="mt-4 text-sm font-semibold">Proposals</h3>
      {r.proposals.length === 0 ? (
        <p className="mt-1 text-sm text-muted">
          None: no group of trades loses clearly enough yet. That is the expected state until there are many closed trades.
        </p>
      ) : (
        <ul className="mt-2 space-y-3">
          {r.proposals.map((p) => (
            <li key={p.id} className="rounded-lg border border-line p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={proposalTone(p.status)}>{p.status}</Badge>
                <span className="text-xs text-muted">
                  #{p.id}, made {shortDate(p.created_at)} ({p.evidence.review_version})
                </span>
              </div>
              <p className="mt-1">{p.text}</p>
              <p className="mt-1 text-xs text-muted">{proposalNext(p)}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ValidationCard({ r }: { r: PaperReview }) {
  const tested = r.proposals.filter((p) => p.validated_at || p.forward);
  return (
    <Card title="Validation" subtitle="Every proposal is tested on data its evidence never saw before anything changes.">
      <ul className="list-disc space-y-1 pl-5 text-sm">
        <li>
          <strong>Backtest:</strong> the strategy with and without the filter, walk-forward with a 12-month holdout, on the
          history before this paper account opened. It passes with at least 100 out-of-sample trades, a better
          out-of-sample expectancy, a positive and better holdout expectancy, and a max drawdown at most 2 points worse.
        </li>
        <li>
          <strong>Forward:</strong> the paper trades signalled after the proposal was made, split by the filter. Reporting
          only.
        </li>
        <li>
          Proposals tested so far, across all strategies: {r.proposals_tested_all}. Each is a trial, so the more are
          tried, the stronger the evidence a pass needs.
        </li>
      </ul>
      {tested.length > 0 && (
        <Table stack>
          <thead>
            <tr>
              <Th>Proposal</Th>
              <Th num>OOS trades</Th>
              <Th num>OOS expectancy</Th>
              <Th num>Holdout</Th>
              <Th num>Max DD</Th>
              <Th>Forward</Th>
            </tr>
          </thead>
          <tbody>
            {tested.map((p) => {
              const b = p.backtest?.base;
              const f = p.backtest?.filtered;
              const pair = (key: string, fmt: (v: number) => string) => (b && f ? `${fmt(b[key])} → ${fmt(f[key])}` : "-");
              return (
                <tr key={p.id}>
                  <Td label="Proposal">
                    #{p.id} <Badge tone={proposalTone(p.status)}>{p.status}</Badge>
                    {p.backtest?.fails?.length ? <div className="text-xs text-muted">{p.backtest.fails.join("; ")}</div> : null}
                    {p.backtest?.reason ? <div className="text-xs text-muted">{p.backtest.reason}</div> : null}
                  </Td>
                  <Td label="OOS trades" num>{pair("oos_trades", String)}</Td>
                  <Td label="OOS expectancy" num>{pair("oos_expectancy_r", rMultiple)}</Td>
                  <Td label="Holdout" num>{pair("holdout_expectancy_r", rMultiple)}</Td>
                  <Td label="Max DD" num>{pair("max_drawdown_pct", (v) => pctText(v))}</Td>
                  <Td label="Forward" className="text-xs">
                    {p.forward
                      ? `${p.forward.trades} trades since ${shortDate(p.forward.since)}: skipped ${p.forward.skipped.trades} at ${rMultiple(p.forward.skipped.avg_r)}, kept ${p.forward.kept.trades} at ${rMultiple(p.forward.kept.avg_r)}${p.forward.trades < 20 ? " (too few to judge)" : ""}`
                      : "-"}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

const KIND_LABELS: Record<AuditEvent["kind"], string> = {
  signal: "Signal",
  entry: "Bought",
  partial_exit: "Sold part",
  exit: "Sold",
  skip: "Skipped",
};

function eventText(e: AuditEvent): string {
  const d = e.detail as Record<string, unknown>;
  if (e.kind === "signal") {
    const zone = d.entry_zone as { low?: string; high?: string } | null;
    return `entry ${zone?.low ?? "-"} to ${zone?.high ?? "-"}, stop ${d.stop ?? "-"}, ${d.shares ?? "-"} shares`;
  }
  if (e.kind === "skip") return String(d.reason ?? e.ref);
  const parts = [`${d.shares ?? "-"} at ${d.price ?? "-"}`];
  if (d.reason) parts.push(String(d.reason));
  if (d.charges !== undefined) parts.push(`charges ₹${d.charges}`);
  return parts.join(", ");
}

function AuditCard({ audit, total }: { audit: AuditEvent[]; total: number }) {
  return (
    <Card
      title="Audit trail"
      subtitle={`Each signal, fill, exit and skip as Jeron first recorded it, never changed. ${total} events in all; the newest ${audit.length} below.`}
    >
      {audit.length === 0 ? (
        <p className="text-sm text-muted">Nothing recorded yet.</p>
      ) : (
        <Table stack>
          <thead>
            <tr>
              <Th>Session</Th>
              <Th>Event</Th>
              <Th>Stock</Th>
              <Th>Detail</Th>
              <Th>Recorded</Th>
            </tr>
          </thead>
          <tbody>
            {audit.map((e) => (
              <tr key={`${e.kind}-${e.event_date}-${e.ticker}-${e.ref}`}>
                <Td label="Session">{shortDate(e.event_date)}</Td>
                <Td label="Event">{KIND_LABELS[e.kind]}</Td>
                <Td label="Stock" className="font-medium">{e.ticker}</Td>
                <Td label="Detail" className="text-xs">{eventText(e)}</Td>
                <Td label="Recorded" className="text-xs text-muted">{new Date(e.recorded_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}
