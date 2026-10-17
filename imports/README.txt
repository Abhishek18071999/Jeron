Drop files here and Jeron imports them by itself within a minute or two (the scheduler
must be running: `docker compose up -d`). You can also upload them on the Setup page.

It reads, by their columns:
- NSE Financial Results CSVs (quarterly results), or a .zip of them
- NSE bulk deals, block deals and insider-trading CSVs
- NSE board-meetings CSV
- the ASM list (with "asm" in the file name)
- Zerodha's tradebook CSV

Each file then moves to done/ or failed/, with a .log file beside it saying what happened.
