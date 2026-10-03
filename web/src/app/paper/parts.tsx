import type { PaperDay, PaperTrade, SignalView } from "@/lib/api";

import { num, rupees, signClass } from "../backtests/format";

export function StageBadge({ stage }: { stage: string }) {
  return stage === "paper" ? (
    <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-800 dark:bg-green-900/40 dark:text-green-300">
      PAPER
    </span>
  ) : (
    <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
      RESEARCH ONLY
    </span>
  );
}

export function EquityLine({ days, capital }: { days: PaperDay[]; capital: number }) {
  if (days.length < 2) return null;
  const W = 800;
  const H = 160;
  const values = days.map((d) => Number(d.equity));
  const min = Math.min(capital, ...values);
  const max = Math.max(capital, ...values);
  const span = max - min || 1;
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => H - ((v - min) / span) * H;
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H + 20}`} className="w-full" role="img" aria-label="Paper equity">
      <line
        x1={0}
        x2={W}
        y1={y(capital)}
        y2={y(capital)}
        className="stroke-neutral-400"
        strokeDasharray="4 4"
      />
      <path d={line} fill="none" className="stroke-blue-600 dark:stroke-blue-400" strokeWidth={2} />
      <text x={0} y={H + 16} className="fill-neutral-500 text-xs">
        {days[0].trade_date}
      </text>
      <text x={W} y={H + 16} textAnchor="end" className="fill-neutral-500 text-xs">
        {days[days.length - 1].trade_date}
      </text>
    </svg>
  );
}

export function TradesTable({ trades, open }: { trades: PaperTrade[]; open: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-neutral-500">
          <tr>
            <th className="py-2 pr-4">Stock</th>
            <th className="pr-4">Entry</th>
            <th className="pr-4 text-right">Price</th>
            <th className="pr-4 text-right">Shares</th>
            <th className="pr-4 text-right">Initial stop</th>
            {open ? (
              <>
                <th className="pr-4 text-right">Stop now</th>
                <th className="pr-4 text-right">Close</th>
              </>
            ) : (
              <>
                <th className="pr-4">Exit</th>
                <th className="pr-4 text-right">Price</th>
              </>
            )}
            <th className="pr-4 text-right">P&amp;L</th>
            <th className="pr-4 text-right">R</th>
            <th>{open ? "Sessions" : "Why it ended"}</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.seq} className="border-t border-neutral-200 dark:border-neutral-800">
              <td className="py-2 pr-4 font-medium">{t.ticker}</td>
              <td className="pr-4">{t.entry_date}</td>
              <td className="pr-4 text-right">{num(t.entry_price)}</td>
              <td className="pr-4 text-right">{open ? `${t.shares_held} of ${t.shares}` : t.shares}</td>
              <td className="pr-4 text-right">{num(t.initial_stop)}</td>
              {open ? (
                <>
                  <td className="pr-4 text-right">{num(t.current_stop)}</td>
                  <td className="pr-4 text-right">{num(t.last_close)}</td>
                </>
              ) : (
                <>
                  <td className="pr-4">{t.exit_date}</td>
                  <td className="pr-4 text-right">{num(t.exit_price)}</td>
                </>
              )}
              <td className={`pr-4 text-right ${signClass(t.net_pnl)}`}>{rupees(t.net_pnl)}</td>
              <td className={`pr-4 text-right ${signClass(t.r_multiple)}`}>{num(t.r_multiple)}</td>
              <td className="text-neutral-500">{open ? t.sessions : t.exit_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-2 py-1">
      <dt className="text-neutral-500">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function SignalCard({ signal }: { signal: SignalView }) {
  const p = signal.payload;
  const b = p.backtest_stats;
  return (
    <details className="rounded border border-neutral-200 p-3 dark:border-neutral-800">
      <summary className="cursor-pointer">
        <span className="font-medium">{p.ticker}</span> on {signal.signal_date}: buy {p.shares} between{" "}
        {num(p.entry_zone.low)} and {num(p.entry_zone.high)}, stop {num(p.stop.price)}, T1 {num(p.targets.t1)}
        {signal.research_only ? (
          <span className="ml-2 text-xs text-amber-700 dark:text-amber-400">research only</span>
        ) : null}
        {signal.late ? <span className="ml-2 text-xs text-neutral-500">recorded late</span> : null}
      </summary>
      <dl className="mt-3 text-sm">
        <Row label="Setup">
          {p.setup_name} ({p.strategy_version}, {p.tier})
        </Row>
        <Row label="Why">
          <ul className="list-disc pl-5">
            {p.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Row>
        <Row label="Entry zone">
          {num(p.entry_zone.low)} to {num(p.entry_zone.high)}, valid on {p.entry_zone.valid_until}
        </Row>
        <Row label="Stop">
          {num(p.stop.price)} ({p.stop.type}): {p.stop.reason}
        </Row>
        <Row label="Targets">
          T1 {num(p.targets.t1)}, T2 {num(p.targets.t2)} ({p.targets.basis})
        </Row>
        <Row label="Reward:risk">
          {num(p.risk_reward_t1)} to T1, {num(p.risk_reward_t2)} to T2, after costs
        </Row>
        <Row label="Size">
          {p.shares} shares, {rupees(p.capital_at_risk)} at risk
        </Row>
        <Row label="Holding">
          {p.expected_holding.min_days} to {p.expected_holding.max_days} sessions; time stop{" "}
          {p.time_stop_days}
        </Row>
        <Row label="Exit plan">{p.exit_plan}</Row>
        <Row label="Invalidation">{p.invalidation}</Row>
        <Row label="Event risk">{p.event_risk}</Row>
        <Row label="Conviction">{p.conviction} of 5</Row>
        <Row label="Brains">
          technical {p.brains_breakdown.technical}, fundamental{" "}
          {p.brains_breakdown.fundamental ?? "not built yet"}, news{" "}
          {p.brains_breakdown.news ?? "not built yet"}, combined {p.brains_breakdown.combined}
        </Row>
        <Row label="Backtest">
          {b.trades} trades, win rate {num(Number(b.win_rate) * 100, 1)}%, expectancy {num(b.expectancy_R, 3)}
          R, profit factor {num(b.profit_factor)}, max drawdown {num(b.max_drawdown_pct, 1)}%; {b.period}
        </Row>
        {p.notes.length ? (
          <Row label="Notes">
            <ul className="list-disc pl-5">
              {p.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </Row>
        ) : null}
        <Row label="Signal id">
          <code className="text-xs">{p.signal_id}</code>
        </Row>
      </dl>
    </details>
  );
}
