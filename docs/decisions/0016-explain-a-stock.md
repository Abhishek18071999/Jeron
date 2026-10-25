# 0016: Explain a stock from Jeron's own numbers

Date: 2026-10-25. Status: built (docs/plans/explain-v1.md).

**Question.** The owner's platform brief asks for an AI research assistant. Spec section 3
limits the LLM to labelling news and says it never produces prices, targets or stops;
remaining-work E decided against an LLM choosing trades. Is there an assistant that
helps decisions without breaking either?

**Decision.**
1. The explanation is built without an LLM (`app/explain/facts.py`, pure): every line is
   a fact with its source, the date it is true for, and its kind (exchange data,
   Jeron's calculation, a model's reading of an announcement, a strategy's rule), and the
   brief built from them (why it is in the scan, what supports it, what argues against
   it, what would cancel the setup, three level-based scenarios, a pre-trade checklist,
   what Jeron doesn't know) is deterministic and tested.
2. The setup check (is the newest signal still valid?) is part of it: invalidated once
   a low reaches the stop, expired when the zone's date passes unfilled, "above zone"
   when the last close is above it (the engine skips such a buy). Prices are adjusted to
   today's basis.
3. The LLM is optional and only words the facts (`app/explain/narrate.py`). It gets the
   facts and nothing else, must cite fact ids per point, and every number it writes must
   appear in the facts that point cites. Advice ("buy now", "you should"), forecasts
   ("will rise"), probabilities and certainty are refused. A reply that fails a check is
   stored as rejected and never shown as the stock's wording; the owner sees why. An
   optional question (300 characters) goes in as data.
4. It uses the news labeller's provider, key and transport (`JERON_NEWS_PROVIDER`), one
   request per narration, and spends from the same monthly cap (recorded in `llm_usage`
   as `explain:<model>`), with at most 50 a day. A narration of the same facts is reused.
   Every one is stored (`explanations`) with the facts it was given.
5. Nothing here places, sizes or changes an order. Sizing stays in the trade plan.
6. Compare (`/stocks/compare`) puts two or three briefs side by side; no LLM.
7. The real account's daily equity (`app/portfolio/equity.py`) is the journal marked at
   each session's close against the Nifty 500 price index, so the drawdown peak includes
   open profit given back before selling (decision 0015, point 2).

**Alternatives.** A free-form chat with tool access to the database: refused by the
brief's own rules (no arbitrary queries, no invented data) and by the spec. Letting the
LLM summarise the stock from raw data: it could invent or round numbers, which the
number check exists to stop.
