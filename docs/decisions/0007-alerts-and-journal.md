# 0007: Alerts through Telegram's Bot API, journal decisions through the web app

Date: 2026-10-03. Status: proposed (M5).

**Decision.**
1. Alerts go out through Telegram's Bot API (`sendMessage`, plain HTTPS with `httpx`, no
   bot library), with SMTP email as the backup. Messages are plain text so Telegram
   and email read the same.
2. One message per new signal of a live-eligible strategy, plus a daily summary after
   every `daily` run (including blocked days, saying why). Research-only signals are
   listed in the summary, not sent one by one, unless a setting turns that on.
3. Every alert is stored in `alerts` under a unique key (signal id, or day for the
   summary). A re-run sends only what failed before; nothing is sent twice.
4. The journal records what I did with each signal (taken, modified, skipped, with my
   fills). Every signal without an entry counts as pending, so nothing is lost. Taking
   or skipping is done on the web page an alert links to; there are no Telegram
   buttons yet.
5. Web forms post through Next.js server actions; the API stays private to the server
   side and CORS stays read-only.

**Why.**
- The Bot API is two HTTPS calls; a library would add a dependency and a long-running
  process for nothing we use yet. Telegram buttons need a process listening for
  replies (polling or a public webhook), which the laptop setup doesn't have.
- Ground rule: no signal without a backtested strategy behind it. Research-only
  signals are evidence, not trades, so they must not arrive looking like trades.
- Storing alerts makes the daily job safe to re-run after a failure.

**Consequences.** The bot token and SMTP password live only in `.env`. Telegram's API
is not reachable from the cloud build container, so the real send is tested on the
laptop (`python -m app.cli telegram --test`). Login (password + TOTP) waits for the
move to a cloud VM; until then the web app must not be exposed beyond the laptop.
