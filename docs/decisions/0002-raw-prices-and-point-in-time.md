# 0002: Store raw prices per source; keep history point-in-time

Date: 2026-09-30. Status: accepted.

**Decision.** `daily_bars` holds raw, unadjusted OHLCV with the data source in the
primary key. Adjusted prices are computed from raw bars and `corporate_actions`.
Index membership has start and end dates; instruments keep their delisting date.

**Why.** Raw data per source lets M1 cross-check two sources day by day and makes
every adjustment explainable. Point-in-time membership, including delisted stocks,
avoids survivorship bias in backtests (spec section 2).

**Consequences.** Queries for adjusted series need a join or a cached view; M1 adds
that.
