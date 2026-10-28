// The Portfolio page's "Bad days" card: what the held stocks' own history says about
// market shocks, one-day losses, gaps through stops and how closely they move together
// (backend app/portfolio/risk.py).
import { Card, Notice, Stat, Table, Td, Th, inr, pctText, shortDate } from "@/components/ui";
import type { PortfolioRisk } from "@/lib/api";

const pctOf = (value: number | null, equity: number) =>
  value === null || !equity ? undefined : `${pctText((value / equity) * 100, 1)} of equity`;

export function RiskCard({ r }: { r: PortfolioRisk }) {
  const beyond = r.stocks.reduce((sum, s) => sum + (s.beyond_stop ?? 0), 0);
  const through = r.stocks.filter((s) => (s.beyond_stop ?? 0) > 0).length;
  return (
    <Card
      title="Bad days"
      subtitle={`From ${r.var_sessions || "too few"} sessions of these stocks' own NSE prices${r.as_of ? ` to ${shortDate(r.as_of)}` : ""}. History, not a forecast.`}
    >
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat
          label="Book beta"
          value={r.book_beta === null ? "-" : r.book_beta.toFixed(2)}
          sub="vs the Nifty 500"
          help="How much the positions moved, on average, for each 1% move of the Nifty 500 over the last year."
          how={`Each stock's beta from up to ${r.beta_sessions} daily returns beside the Nifty 500's, weighted by its value today. 1.3 means a 1% index day moved the book about 1.3%.`}
        />
        <Stat
          label="1-day 95% VaR"
          value={r.var95 === null ? "-" : inr(r.var95, 0)}
          sub={pctOf(r.var95, r.equity)}
          tone={r.var95 !== null && r.equity && r.var95 / r.equity > 0.02 ? "warn" : "neutral"}
          help="The loss today's positions would have passed on 1 day in 20 of the history."
          how={`Today's shares were run through each of the last ${r.var_sessions} sessions' actual returns, every stock on the same day, so the way they fall together is the market's, not a model's. 99%: ${r.var99 === null ? "-" : inr(r.var99, 0)}. The average of the worst 2.5% of days: ${r.es97 === null ? "-" : inr(r.es97, 0)}.`}
        />
        <Stat
          label="Worst day in the history"
          value={r.worst_day_loss === null ? "-" : inr(-r.worst_day_loss, 0)}
          sub={r.worst_day ? shortDate(r.worst_day) : undefined}
          help="The worst single session for today's positions over the history."
          how="The same simulation as the VaR: the largest one-day loss."
        />
        <Stat
          label="Worst gaps past the stops"
          value={inr(-beyond, 0)}
          tone={beyond > 0 ? "warn" : "neutral"}
          sub={
            through
              ? `${through} of ${r.stocks.length} stocks have gapped further than their stop is away`
              : "no stock's worst gap reaches its stop"
          }
          help="What a stock's worst opening gap of the history would cost beyond its stop, if it came tomorrow."
          how={`Each stock's worst gap down (open against the previous close) applied to its last close. A stop can't sell above the open, so a gap past the stop loses more than planned. Every stop filling at its price loses ${inr(r.planned_loss, 0)}; every stock opening at its worst gap at once, ${inr(r.gap_loss, 0)}.`}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-medium text-muted">If the Nifty 500 fell in a day</h3>
          <Table>
            <thead>
              <tr>
                <Th>Nifty 500</Th>
                <Th num>Loss before stops</Th>
                <Th num>Of equity</Th>
              </tr>
            </thead>
            <tbody>
              {r.shocks.map((s) => (
                <tr key={s.index_move_pct}>
                  <Td>{pctText(s.index_move_pct, 0)}</Td>
                  <Td num className="text-bad">
                    {inr(-s.loss, 0)}
                  </Td>
                  <Td num>{pctText(s.loss_pct, 1)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <p className="mt-1 text-xs text-muted">
            Each stock moving by its beta. In a crash stocks fall together more than usual, so read these as
            the least it could be.
          </p>
        </div>
        <div>
          <h3 className="mb-1 text-xs font-medium text-muted">Moving together</h3>
          <p className="text-sm">
            {r.avg_correlation === null
              ? "Needs two positions with enough history."
              : `Average correlation ${r.avg_correlation.toFixed(2)} over the last ${r.corr_sessions} sessions.`}
          </p>
          {r.high_pairs.length > 0 ? (
            <ul className="mt-1 space-y-0.5 text-sm">
              {r.high_pairs.map((p) => (
                <li key={`${p.a}-${p.b}`}>
                  <span className="font-medium">{p.a}</span> and <span className="font-medium">{p.b}</span>:{" "}
                  {p.correlation.toFixed(2)}, closer to one position than two
                </li>
              ))}
            </ul>
          ) : (
            r.avg_correlation !== null && (
              <p className="mt-1 text-sm text-muted">No pair above {r.high_corr.toFixed(1)}.</p>
            )
          )}
        </div>
      </div>

      <div className="mt-4">
        <Table stack>
          <thead>
            <tr>
              <Th>Stock</Th>
              <Th num>Weight</Th>
              <Th num>Beta</Th>
              <Th num>Volatility</Th>
              <Th num>Worst gap</Th>
              <Th num>To the stop</Th>
              <Th num>At the worst gap</Th>
            </tr>
          </thead>
          <tbody>
            {r.stocks.map((s) => (
              <tr key={s.ticker}>
                <Td label="Stock" className="font-medium">
                  {s.ticker}
                </Td>
                <Td label="Weight" num>
                  {pctText(s.weight_pct, 0)}
                </Td>
                <Td label="Beta" num>
                  {s.beta === null ? "-" : s.beta.toFixed(2)}
                </Td>
                <Td label="Volatility" num>
                  {s.volatility_pct === null ? "-" : `${pctText(s.volatility_pct, 0)} a year`}
                </Td>
                <Td label="Worst gap" num>
                  {s.worst_gap_pct === null ? "-" : pctText(s.worst_gap_pct, 1)}
                  {s.worst_gap_day && <span className="ml-1 text-xs text-muted">{shortDate(s.worst_gap_day)}</span>}
                </Td>
                <Td label="To the stop" num>
                  {s.planned_loss === null ? "no stop" : inr(-s.planned_loss, 0)}
                </Td>
                <Td label="At the worst gap" num className={s.beyond_stop ? "text-bad" : ""}>
                  {s.gap_loss === null ? "-" : inr(-s.gap_loss, 0)}
                  {!!s.beyond_stop && (
                    <span className="block text-xs">{inr(s.beyond_stop, 0)} past the stop</span>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
      {r.notes.length > 0 && (
        <div className="mt-3 space-y-2">
          {r.notes.map((n) => (
            <Notice key={n}>{n}</Notice>
          ))}
        </div>
      )}
    </Card>
  );
}
