# Compare stocks v2

Follows explain-v1 (decision 0016). Asked for: the compare page wasn't working, its search
should work like the rest of the app, the comparison should be clearer, and the
strategies should say how to use them.

## What was wrong

- One symbol with no prices (a typo, a company name, an old symbol) failed the whole
  comparison with "No prices stored for ...".
- Names ("tata steel") and symbols separated by spaces were taken as one symbol.
- A free-text box with no suggestions, unlike the header's search.
- On phones the four-column table was squeezed into narrow columns.
- Not reachable from Stocks or Ctrl+K (the palette's "Compare" opened backtest vs paper).

## What changed

- `GET /stocks/compare` returns `{briefs, not_found}`. Each entry is a symbol or, failing
  that, the search box's first match (name, short name, old symbol); the same stock asked
  twice is shown once. Facts carry their `number`; a brief carries its signal's
  `strategy` and `research_only`.
- Web: chips plus the shared `StockSearch` (new `onPick`); per-stock cards (close, setup,
  signal, for/against, checks not met, stock page and trade plan); "Where they differ"
  (rows Jeron's rules read for one stock and against another); grouped rows with a "?"
  per row and a ▲/▼ mark on the number the rules treat as stronger, only on rows with a
  direction (not RSI, ATR, P/E); a phone layout with the label above the columns.
- Strategy guidance (`src/lib/strategy-guide.ts`): what each strategy looks for, when it
  works, its section and hold, the steps from signal to exit with the signal's own
  levels, its own exit rule, and its lesson. Shown on Compare, on the stock page's brief
  ("How to use this signal") and linked from every signal row's strategy key.
- The strategy record fact no longer nests brackets.

Nothing here is a verdict: marks say which number is higher or lower and why that
direction matters to Jeron's rules, not which stock to buy.

## Tests

`tests/test_explain_db.py` (misses listed, names matched, duplicates merged, `number`,
`strategy`); `web/src/lib/compare.test.ts`; `web/src/lib/strategy-guide.test.ts` (every
strategy key in `strategies.py` has a guide, every linked lesson exists, steps follow the
section's rules).
