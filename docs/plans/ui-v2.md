# UI v2: the five changes from the UI/UX wishlist

Status: built on `claude/finish-remaining-work-0p0v8g`.

## Goal
The top five of the UI/UX wishlist (the "Jeron explained" doc, UI/UX wishlist tab, 12 Oct
2026): make the morning routine a one-minute job on a phone, show trades as pictures,
and let every number explain itself. Nothing here changes a strategy, a risk rule or a
number the engine computes; it changes how they are shown.

## What is built
1. **Morning briefing** (Today). The "Actions due" card becomes one line per action,
   verb first: "Sell all 80 AZAD", "Buy 121 STK4" with the pre-open order steps, "Check
   X by hand", "Park ₹X of idle cash", "Record what you did with X". Each has a tick box;
   ticks are kept per day in the browser, and the card says "Done for today" when all
   are ticked. A one-sentence headline says what the morning holds. Built from the
   pre-open exit plan and the pending signals (`web/src/lib/briefing.ts`, pure).
2. **Trade picture.** Entry, stop and targets on the chart of the stock page (my open
   position's levels first, else the latest signal's) and of the trade plan; an "R
   ruler" from -1R to +3R showing where the price sits, on the stock page, trade plan,
   signal page, journal entry and each phone position card
   (`web/src/components/trade-picture.tsx`). Chart prices are split/bonus-adjusted, as
   before; journal prices are raw, so a split while holding shifts the chart lines.
3. **Tap to explain.** A number with an explanation is tappable (dotted underline); it
   opens a sheet (bottom sheet on phones) with what it is and, where given, how Jeron
   works it out. The 14px "?" icons become 24px tap targets that open the same sheet
   (`web/src/components/explain.tsx`).
4. **Telegram buttons** under each signal alert: "I bought it", "Skip, with reason", and
   "Open plan" when `JERON_WEB_URL` is an address Telegram accepts (not localhost).
   - Skip swaps the buttons for six reasons; a tap records the skip in the journal.
   - I bought it records the signal as taken and asks for "shares price" in a forced
     reply naming the signal; the reply adds the buy fill (today, charges estimated
     like a tradebook import). The tradebook import later adds the broker's own fill,
     so check the journal then and delete one of the two.
   - The scheduler reads presses every minute while Telegram is set up
     (`app/alerts/bot.py`). Only the configured chat counts; each update is stored once
     in `bot_updates`, so nothing is recorded twice. A signal with a buy recorded can't
     be skipped from Telegram.
5. **Phone fixes.** Tables on the stock page (deals, insider trades, results), the
   watchlist and the portfolio become cards on phones (`Table stack`); one date style
   ("Fri, 9 Oct", the year only when it isn't this year) on the everyday screens;
   terminal commands are hidden on phones (a plain sentence instead) and get a Copy
   button on computers.

## Left out on purpose
Live prices, one-tap buying, streaks and badges (the wishlist's "not adding" list).
Research pages (backtests, data quality, spot check) keep ISO dates, which match the
files they are checked against.
