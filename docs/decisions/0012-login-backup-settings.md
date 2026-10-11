# 0012: Login, nightly backup, Settings page and a cost cap for news labels

Date: 2026-10-11. Status: proposed.

**Why now.** Spec sections 9 and 10 ask for a single-user login (password + TOTP), a
nightly database backup, a Settings page and a monthly cost cap for the LLM. None
existed, and the first two are needed before Jeron moves to a cloud VM.

**Decision.**
1. **Login in the web app.** The browser only ever talks to the web app (server
   components and server actions call the API), so the check sits there:
   `web/src/proxy.ts` sends every page, server action and route handler to `/login`
   without a valid session (route handlers get 401). The password is checked against
   an scrypt hash and the code against a TOTP secret, both in `.env`, made by
   `python -m app.cli auth-setup` (`backend/app/auth.py`; `web/src/lib/auth.ts` reads the
   same formats). The session is a signed cookie for 30 days; its key is derived from
   the hash and the secret, so changing either logs every device out. A code is
   accepted once; five wrong tries lock the login for 15 minutes.
   - Until it is set up, Jeron stays locked and the login page says how to set it up.
     `JERON_LOGIN_DISABLED=true` turns it off, with a warning on every page (CI uses it).
   - The API has no login of its own: keep its port bound to 127.0.0.1 (as in
     `docker-compose.yml`) and never expose it.
   - The cookie is `Secure` only over https, because the phone opens Jeron over http on
     the home network.
2. **Backup.** A `backup` service (postgres image, `backup/backup.sh`) runs `pg_dump`
   once a day after 02:00 IST, or when the machine is next on, into `backups/` (or
   `JERON_BACKUP_DIR`), keeping the newest 14. Downloaded NSE files are not backed up:
   they can be downloaded again.
3. **Settings page** (`/settings`). Capital, risk %, position limits, sector cap,
   research-signal alerts and the news cap can be changed there. The `.env` values stay
   the defaults; a change is a new `setting_changes` row (never updated), and the latest
   per key wins (`app/settings_store.py`, `effective_settings`). Secrets stay in `.env`
   only; the page shows whether they are set, never their values. Paper accounts keep
   the values they opened with.
4. **News cost cap.** Every labelling chunk and collected batch stores its tokens and
   estimated US$ (`llm_usage`, list prices in `app/news/claude.py`). Before each chunk
   the labeller checks the month's spend (IST calendar month) against
   `JERON_NEWS_MONTHLY_BUDGET_USD` (default US$20, 0 = no cap) and stops when it is
   reached; batches are trimmed to what the cap leaves after the batches still running.
   Ollama Cloud has no list price here and isn't counted.

**Not done.** Moving to a cloud VM (https in front, then the cookie is `Secure`), and
copying backups off the machine automatically.
