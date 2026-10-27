# Runbook: what to do when something looks wrong

Short, so it can be followed in a hurry. The rule behind every entry: when in doubt,
stop new buys first (one command), protect open positions with the stops already at the
broker, then find out. Jeron never places orders, so stopping Jeron never strands a
position; it only stops new ideas.

Commands run from the repo folder. On the laptop they are
`docker compose exec backend python -m app.cli ...`; below they are shortened to
`jeron ...`.

## The kill switch

```
jeron stop-all --reason "NSE data looks wrong"
jeron resume
```

`stop-all` (decision in `docs/plans/review-v1.md`, code in `backend/app/halt.py`):

- no signal or watchlist alerts; the daily summary and the 08:30 pre-open check still
  come, headed **JERON IS STOPPED** with your reason, because open positions still
  need their exits;
- new signals are recorded as research only and stay so after `resume` (signals are
  never changed);
- the Trade page refuses to save a plan ("Kill switch off" fails);
- paper trading carries on, so the paper record has no gap.

It sends one Telegram message saying it is on, and `resume` one saying it is off. Every
stop and resume is kept in `setting_changes` (key `halt`).

## Incidents

### No daily summary by 19:45

The dead-man's switch sends **JERON DID NOT FINISH TONIGHT'S RUN** if the summary (or
the "data has not arrived" alert) hasn't gone out by `JERON_SCHEDULE_WATCHDOG`. It says
whether a run is still going.

1. "A run is still going": wait 30 minutes. Still nothing: `docker compose logs
   scheduler --tail 100` and look for the step it is on (a news-labelling batch or an
   NSE download retrying are the usual ones).
2. "No run is going": `docker compose ps`. A service that isn't `running`:
   `docker compose up -d`. Then `jeron daily` by hand and read its output.
3. It says the scan was blocked: the quality report says why (next section).
4. Don't act on the previous day's signals; they were valid for one session.

If you get **no message at all** (not even the watchdog's), the laptop, Docker or the
scheduler is down; only the outside heartbeat can tell you that. See "Heartbeat" below.

### Data looks wrong (a price, a gap, a stock "crashed" 40%)

1. `jeron stop-all --reason "checking <SYMBOL> prices"`.
2. Open Research > Spot check for the stock and date: raw vs adjusted prices, the
   second source, the adjustment log. Compare with the broker's chart.
3. A demerger or rights issue: since decision 0017 Jeron adjusts both (rights by the
   theoretical ex-rights price, demergers by the ex-date's special pre-open price). The
   adjustment log shows the factor used. One it could not price (no issue price in
   NSE's text, a premium too small to price without the face value, a scheme of
   arrangement) stays flagged by quality check #9: signals
   HELD, exits under CHECK BY HAND. Decide by hand: the broker's adjusted chart is the
   reference.
4. A bad close from NSE (the second source disagrees by more than 0.5% and nothing
   explains it): the quality report marks it. Re-download the day with
   `jeron backfill --start <day> --end <day> --force`, then `jeron quality --start <day>
   --end <day>` and `jeron daily`.
5. `jeron resume` when the numbers match the broker.

### An alert looks wrong (a signal you don't believe, a stop that makes no sense)

1. Don't trade it. Nothing is lost by skipping one signal; skip it in the journal with
   the reason, so the skip is counted.
2. Open the signal's plan (the alert's "Open plan" button or Trade). The plan re-checks
   size, stop distance, heat, sector, results blackout and the guardrails on today's
   numbers. A plan that fails says why.
3. If several alerts look wrong, it is the data, not the signal: `jeron stop-all` and
   follow "Data looks wrong".
4. A stop in the pre-open check that differs from yours at the broker: the check's
   "STOPS AT THE BROKER" list is what the exit rules say after the last close. Set the
   broker's GTT to it, or record why you didn't.

### Alerts stopped arriving

`jeron telegram --test`. A failure names the cause (token revoked, chat id changed,
network). Email is the backup channel (`JERON_SMTP_*`). Re-sent alerts are safe: each
is stored once and only failed ones are retried.

### The market is in turmoil (a crash day, circuit breakers)

Nothing to do in Jeron. The rules already halve risk in risk-off markets, stop new
entries at 6% heat and pause them after a 15% drawdown. If you want no new ideas until
it settles, `jeron stop-all --reason "market turmoil"`: your exits keep coming.

## Heartbeat: knowing when Jeron is off

A computer that is asleep can't say so. Jeron calls `JERON_HEARTBEAT_URL` after every
finished daily run; an outside monitor that expects that call each weekday evening
alerts you when it doesn't come. Optional, your choice of service (spec section 0,
rule 6). With healthchecks.io's free plan:

1. Create a check; schedule `45 19 * * 1-5`, time zone Asia/Kolkata, grace 2 hours.
   It will also expect a ping on NSE holidays: pause the check on those days, or accept
   one alert on each.
2. Add its Telegram or email integration.
3. Put the ping URL in `.env` as `JERON_HEARTBEAT_URL=...` and `docker compose up -d`.

## Restore drill (once a quarter)

The backup service already restores the newest dump into a scratch database every week
and reports it on Setup and in the pre-open check. That proves the dump is readable.
The drill proves you can get your journal back on another computer, which is the case
that matters. Put it in your calendar for the first weekend of January, April, July
and October. About 30 minutes.

1. Copy the newest `backups/jeron-YYYY-MM-DD.dump` to a USB stick or cloud folder,
   as you would if the laptop died.
2. On any computer with Docker (or the same one, in a second folder): clone the repo,
   copy `.env`, `docker compose up -d db`.
3. Restore:
   `docker compose exec -T db pg_restore -U jeron -d jeron --clean --if-exists < jeron-YYYY-MM-DD.dump`
4. `docker compose up -d`. Check: the Journal shows your positions and fills; Portfolio
   matches the broker's holdings; Setup shows prices up to the dump's date; the next
   daily run fills in the days since.
5. Write the date and the result here:

| Date | Dump | Restored on | Journal matches broker | Notes |
|---|---|---|---|---|
| | | | | |

## A week without Jeron (what breaks, what comes back)

If the laptop dies or is away for a week:

| | Comes back by itself | Lost or needs you |
|---|---|---|
| Prices (bhavcopy), corporate actions, board meetings, announcements | Yes: the next daily run downloads every missed day from NSE's archive | |
| Index closes, security list, Nifty 500 list | Yes (`lists`) | |
| Second-source cross-check (Yahoo) | Yes | |
| Scans | Yes: the catch-up runs the newest session; older days with `jeron scan --date` if wanted | Signals for missed days are recorded late and never alerted (they were valid for one session) |
| Paper accounts | Yes: they are replayed from their first day every run | |
| News labels | Yes: the backlog is labelled (within the monthly cap) | |
| Bulk and block deals | | NSE's archive keeps only the current day: missed days are gone unless saved from nseindia.com (`deals-import`) |
| Telegram button presses | | Telegram keeps them 24 hours: record those decisions in the journal by hand |
| Your real trades | | Only what you enter (or a Zerodha tradebook import, which has everything) |
| Open positions' exits | | No pre-open check while off: keep GTT stops at the broker for every position, always |
| The journal and settings | Only from a backup | A dead disk without an off-laptop copy of `backups/` loses them |

So the urgent risks of being on a laptop are two, and neither needs the cloud: GTT stops
at the broker for every open position (the pre-open check lists them), and a copy of
the backups off the laptop (the drill above). A small cloud VM would add a running
pre-open check and alerts while the laptop is off. Worth it once real money is at the
"full capital" stage (spec section 7), not before.
