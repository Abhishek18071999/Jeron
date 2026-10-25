# 0015: Guardrails on the real account, and an API token

Date: 2026-10-25. Status: built (docs/plans/platform-audit-v1.md).

**Question.** The audit of 2026-10-25 found that spec section 5's drawdown brake and
the max open positions per tier were enforced in the engine (backtests and paper) but not
in the trade plan for real money, and that the backend API had no authentication. How
should each be added without changing any strategy's results?

**Decision.**
1. The guardrails live in the trade plan (`app/plan/calc.py` `guardrails`), the step
   before every real buy, not in the engine: the engine's rules and the golden trades are
   unchanged, and no strategy needs a new version.
2. The account state comes from the journal (`app/portfolio/calc.py` `account_state`):
   equity = `JERON_CAPITAL` + realised gains (first in, first out, after charges) + open
   positions at the last close. The peak is the highest of capital plus the running
   realised total on each sale day, and today's equity. There is no daily mark of the
   journal, so a paper peak given back before selling is missed and the drawdown can
   read lower than the broker's. A daily equity history of the journal would fix that;
   it is not built.
3. Spec rules are always hard: 10% below the peak halves the risk per trade (multiplied
   with the mood's halving, as the engine does), 15% blocks new plans, and the tier's
   open positions are capped by `JERON_MAX_POSITIONS_<TIER>`. The brief's extra limits
   (daily and weekly realised loss, new positions a week) are settings, 2% / 4% / 5 by
   default, blocking unless `JERON_RISK_LIMITS_BLOCK` is off. Realised only: a loss on
   paper is in the drawdown, not in the daily limit.
4. Jeron never places orders (spec section 12), so a block stops a plan from being saved
   and says why; it cannot stop an order typed at the broker.
5. The API checks the Host header against `JERON_ALLOWED_HOSTS` (DNS rebinding) and, with
   `JERON_API_TOKEN` set, a bearer token on every route but `/health`. The token is
   optional so a `git pull` doesn't lock out an install whose `.env` lacks it; the Setup
   page asks for it and `auth-setup` / `api-token` print one.

**Alternatives.** Enforcing the brake in the engine for paper accounts too: already
there. A session cookie shared with the API: the browser never calls the API, so a
server-to-server token is simpler.
