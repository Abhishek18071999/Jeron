import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import { Card, ResearchBadge, SignalRow, inr, rMultiple } from "@/components/ui";
import { type Dashboard, fetchHealth, getJson } from "@/lib/api";

import { signClass } from "./backtests/format";

export const dynamic = "force-dynamic";

const regimeStyle = {
  bull: "border-green-300 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-950/40 dark:text-green-200",
  bear: "border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200",
  sideways:
    "border-neutral-300 bg-neutral-50 text-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-200",
};

function RegimeBanner({ regime }: { regime: Dashboard["regime"] }) {
  if (!regime) {
    return (
      <p className="rounded-lg border border-neutral-300 px-4 py-3 text-sm dark:border-neutral-700">
        Market regime unknown: no Nifty 500 closes stored (run <code>lists</code>).
      </p>
    );
  }
  return (
    <div className={`rounded-lg border px-4 py-3 ${regimeStyle[regime.regime]}`}>
      <span className="font-semibold uppercase">{regime.regime} market</span>
      <span className="text-sm"> · {regime.rule}</span>
      {regime.risk_off && (
        <span className="ml-2 text-sm font-semibold">Regime filter ON: risk per trade halved</span>
      )}
    </div>
  );
}

export default async function Home() {
  const [result, health] = await Promise.all([getJson<Dashboard>("/dashboard"), fetchHealth()]);
  const db = health?.database === "ok";
  const system = (
    <p className="text-xs text-neutral-500">
      Backend:{" "}
      <span className={health ? "text-green-600" : "text-red-600"}>
        {health ? "running" : "not reachable"}
      </span>
      {" · "}Database:{" "}
      <span className={db ? "text-green-600" : "text-red-600"}>{db ? "connected" : "not connected"}</span>
    </p>
  );
  if (!result.ok) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-2xl font-semibold">Jeron</h1>
        <p className="my-4 text-red-600">{result.error}</p>
        {system}
      </main>
    );
  }
  const d = result.data;
  const live = d.signals.filter((s) => !s.research_only);
  const research = d.signals.filter((s) => s.research_only);
  const alertsOn = d.alerts.telegram || d.alerts.email;

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-2xl font-semibold">Today{d.as_of ? ` · ${d.as_of}` : ""}</h1>
        <form action="/stocks" className="flex gap-2">
          <input
            name="symbol"
            placeholder="Stock, e.g. RELIANCE"
            className="w-48 rounded border border-neutral-300 bg-transparent px-2 py-1 text-sm uppercase dark:border-neutral-700"
          />
          <button className="rounded border border-neutral-300 px-3 py-1 text-sm dark:border-neutral-700">
            Open
          </button>
        </form>
      </div>

      <RegimeBanner regime={d.regime} />

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Data quality">
          {d.quality ? (
            <div className="space-y-1 text-sm">
              <p className="flex items-center gap-2">
                <StatusBadge status={d.quality.status} />
                <Link href={`/data/quality/${d.quality.trade_date}`} className="underline">
                  {d.quality.trade_date}
                </Link>
              </p>
              {d.quality.reasons.slice(0, 3).map((r) => (
                <p key={r} className="text-neutral-500">
                  {r}
                </p>
              ))}
            </div>
          ) : (
            <p className="text-sm text-neutral-500">No report yet.</p>
          )}
        </Card>
        <Card title="Scan">
          {d.scan ? (
            <div className="space-y-1 text-sm">
              <p>
                {d.scan.status === "ok"
                  ? `${d.scan.universe_size.toLocaleString("en-IN")} stocks scored`
                  : "Blocked"}
              </p>
              {d.scan.reasons.map((r) => (
                <p key={r} className="text-red-600">
                  {r}
                </p>
              ))}
              <p className="text-neutral-500">
                Top:{" "}
                {d.scan.top.slice(0, 5).map((t, i) => (
                  <span key={t.symbol}>
                    {i > 0 && ", "}
                    <Link href={`/stocks/${t.symbol}`} className="underline">
                      {t.symbol}
                    </Link>{" "}
                    {Number(t.score).toFixed(0)}
                  </span>
                ))}
              </p>
            </div>
          ) : (
            <p className="text-sm text-neutral-500">No scan yet.</p>
          )}
        </Card>
        <Card title="Alerts">
          <div className="space-y-1 text-sm">
            <p>
              {alertsOn
                ? `On: ${[d.alerts.telegram && "Telegram", d.alerts.email && "email"].filter(Boolean).join(" + ")}`
                : "Not set up (see .env.example)"}
            </p>
            {d.last_summary && (
              <p className="text-neutral-500">
                Last summary {d.last_summary.trade_date}:{" "}
                <span className={d.last_summary.status === "sent" ? "" : "text-red-600"}>
                  {d.last_summary.status}
                  {d.last_summary.channel ? ` by ${d.last_summary.channel}` : ""}
                </span>
              </p>
            )}
          </div>
        </Card>
      </div>

      <Card title={`Signals${d.as_of ? ` for ${d.as_of}` : ""}`}>
        {live.length === 0 && (
          <p className="text-sm text-neutral-500">
            No signals from a live strategy
            {d.accounts.some((a) => a.stage === "paper")
              ? "."
              : " (no strategy has passed the backtest bar yet)."}
          </p>
        )}
        {live.length > 0 && (
          <ul>
            {live.map((s) => (
              <SignalRow key={s.signal_id} s={s} />
            ))}
          </ul>
        )}
        {research.length > 0 && (
          <details className="mt-3">
            <summary className="cursor-pointer text-sm text-neutral-500">
              {research.length} research-only signals (paper-traded for evidence, not trades)
            </summary>
            <ul className="mt-2">
              {research.map((s) => (
                <SignalRow key={s.signal_id} s={s} action="Journal" />
              ))}
            </ul>
          </details>
        )}
      </Card>

      {d.pending.length > 0 && (
        <Card title={`Waiting for your decision (${d.pending.length})`}>
          <ul>
            {d.pending.map((s) => (
              <SignalRow key={s.signal_id} s={s} />
            ))}
          </ul>
        </Card>
      )}

      <Card
        title="My open positions"
        action={
          <Link href="/journal" className="text-sm underline">
            Journal
          </Link>
        }
      >
        {d.journal_positions.length === 0 ? (
          <p className="text-sm text-neutral-500">None in the journal.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-neutral-500">
              <tr>
                <th className="py-1">Stock</th>
                <th className="text-right">Shares</th>
                <th className="text-right">Avg entry</th>
                <th className="text-right">Stop</th>
                <th className="text-right">Close</th>
                <th className="text-right">R so far</th>
              </tr>
            </thead>
            <tbody>
              {d.journal_positions.map((e) => (
                <tr key={e.id} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="py-1">
                    <Link href={`/journal/${e.id}`} className="font-medium underline">
                      {e.ticker}
                    </Link>
                  </td>
                  <td className="text-right">{e.position.held}</td>
                  <td className="text-right">{inr(e.position.avg_entry)}</td>
                  <td className="text-right">{inr(e.stop)}</td>
                  <td className="text-right">{inr(e.last_close)}</td>
                  <td className={`text-right ${signClass(e.position.r_multiple ?? 0)}`}>
                    {rMultiple(e.position.r_multiple)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card
        title="Paper accounts"
        action={
          <Link href="/paper" className="text-sm underline">
            Paper trading
          </Link>
        }
      >
        {d.accounts.length === 0 ? (
          <p className="text-sm text-neutral-500">None yet (run the paper job).</p>
        ) : (
          <div className="space-y-4">
            {d.accounts.map((a) => {
              const positions = d.paper_positions.filter((p) => p.account_id === a.id);
              return (
                <div key={a.id}>
                  <p className="flex flex-wrap items-center gap-2 text-sm">
                    <Link href={`/paper/${a.id}`} className="font-medium underline">
                      {a.strategy_key}
                    </Link>
                    <ResearchBadge research={a.stage !== "paper"} />
                    <span>
                      {inr(a.equity, 0)}{" "}
                      <span className={signClass(a.return_pct)}>
                        ({Number(a.return_pct) >= 0 ? "+" : ""}
                        {Number(a.return_pct).toFixed(2)}%)
                      </span>
                    </span>
                    <span
                      className={Number(a.heat_pct) >= 5 ? "font-semibold text-red-600" : "text-neutral-500"}
                    >
                      heat {Number(a.heat_pct).toFixed(1)}%
                    </span>
                    <span className="text-neutral-500">drawdown {Number(a.drawdown_pct).toFixed(1)}%</span>
                  </p>
                  {positions.length > 0 && (
                    <p className="mt-1 text-sm text-neutral-500">
                      {positions.map((p, i) => (
                        <span key={`${p.ticker}-${p.entry_date}`}>
                          {i > 0 && " · "}
                          <Link href={`/stocks/${p.ticker}`} className="underline">
                            {p.ticker}
                          </Link>{" "}
                          <span className={signClass(p.r_multiple)}>{rMultiple(p.r_multiple)}</span>
                        </span>
                      ))}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>
      <p className="text-xs text-neutral-500">
        Results dates, fundamentals and news arrive with M6. Decision support, not advice.
      </p>
      {system}
    </main>
  );
}
