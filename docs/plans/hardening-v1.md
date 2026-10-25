# Hardening v1: security fixes, backups you can restore, broker stops

Written 2026-10-25, after the platform audit (`docs/plans/platform-audit-v1.md`, PR #35).
The question was "what still puts real money or the owner's records at risk", ranked by
how much it costs if it goes wrong and how little it takes to fix.

## 1. Security

- **Vulnerable dependencies.** `npm audit` on `main` reported Next.js 16.3.8 inside three
  critical advisories (GHSA-2464-fhr4-w9xw, GHSA-p3m5-59mp-jv5r, GHSA-673q-mjm6-r5xr,
  all `>=16.0.0 <=16.4.0`). `pip-audit` reported certifi 2026.7.22 and
  opentelemetry-api 1.45.0. Upgraded: Next.js and eslint-config-next 16.4.2, certifi
  2026.10.23, opentelemetry-api 1.45.1, zod 4.6.7 (dev only). A `dependencies` job in
  CI runs `pip-audit` and `npm audit --omit=dev --audit-level=high` so a new advisory
  turns CI red.
- **Login open redirect.** `safeNext` let `/\evil.com` and `/<tab>/evil.com` through;
  browsers read both as `//evil.com`, so a crafted login link sent the owner to another
  site after a real login. Moved to `src/lib/auth.ts` and tested.
- **Security headers** on every page (`web/next.config.ts`): no framing
  (clickjacking on Settings or the journal), `nosniff`, `same-origin` referrer, no
  camera/microphone/location. No `script-src` policy: Next.js's inline scripts would
  need a nonce on every page.

## 2. Backups you can restore

A nightly `pg_dump` existed, but nothing checked that it could be restored, and nothing
told the owner when the backup service stopped. The journal of real trades is the one
thing Jeron can't download again.

- `backup.sh` keeps a dump only if `pg_restore --list` can read it, and once a week
  restores the newest into a scratch database (`jeron_restore_check`, dropped after),
  counting journal entries, fills, price rows and signals into `restore-check.txt`.
  `sh /backup.sh verify` runs it by hand.
- `app/backups.py` reads the folder (mounted read only in the backend and scheduler)
  for the Setup page and the pre-open check: newest backup over 48 hours old, a failed
  restore test, or backups on the same disk as the database.
- CI's compose job runs `backup.sh verify` and checks the Setup step.

## 3. Broker stops (GTT)

Jeron's exit plan moves the stop to breakeven at +1R and after T1, and halves the
position at T1. The broker only knows the GTT stop the owner set on the day of the buy,
so a gap down after the stop moved, or a GTT still sized for the full position after
booking half, costs real money that the backtest never lost.

- `ExitPlan.stop_before` / `stop_raised`: the stop before the last session's bar.
- `app.exits.job.broker_stop`: the GTT to keep after the next open (shares and
  trigger); none when the plan sells everything; after booking half, the engine's
  remainder (`shares - shares // 2`).
- The pre-open alert lists "STOPS AT THE BROKER", marking a stop the last close raised;
  Portfolio shows the GTT per position; Today's briefing adds "Raise the GTT stop on X"
  and, after "Sell half", the GTT for the shares left.

The trail after T1 is on a closing basis and can't be a GTT; the alert already says
"sell at the next open after a close below".

## Not done here

- Core and satellite allocation (an index fund core beside Jeron's trades): it needs
  the owner's idle-cash decision (remaining-work A6) and changes position sizing, so it
  waits for that decision.
- A `script-src` Content Security Policy with nonces.
