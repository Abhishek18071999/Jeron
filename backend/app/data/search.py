"""Stock search for the search box: symbols, company names, short names and old symbols.

Pure: the database layer passes in the listings, the symbol renames and the aliases.
"""

import csv
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

ALIAS_FILE = Path(__file__).with_name("stock_aliases.csv")

# Words left out of a company's initials ("State Bank of India" -> SBI).
_SKIP = {"OF", "AND", "THE"}
# Initials shorter than this match too many companies to be useful.
_MIN_INITIALS = 3


@dataclass(frozen=True)
class Listing:
    symbol: str
    name: str | None
    series: str


@dataclass(frozen=True)
class Match:
    symbol: str
    name: str | None
    series: str
    # The short name or old symbol the query matched ("RIL", "was ZOMATO"), if any.
    alias: str | None = None


def key(text: str) -> str:
    """Letters and digits only, upper case: "tata steel" and "L&T" become TATASTEEL, LT."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def initials(name: str) -> set[str]:
    """A company's initials, with and without "Limited": RIL and RI for Reliance Industries
    Limited, SBI for State Bank of India."""
    words = [w for w in re.findall(r"[A-Z0-9]+", name.upper()) if w not in _SKIP]
    found = {"".join(w[0] for w in words)}
    if words and words[-1] in {"LIMITED", "LTD"}:
        found.add("".join(w[0] for w in words[:-1]))
    return {f for f in found if len(f) >= _MIN_INITIALS}


def load_aliases(path: Path = ALIAS_FILE) -> dict[str, str]:
    with path.open(newline="") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return {key(row["alias"]): row["symbol"].strip() for row in rows}


def latest_symbols(renames: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Old symbol -> the symbol it trades under now, following chains (LTI -> LTIM -> LTM)."""
    step = dict(renames)
    latest: dict[str, str] = {}
    for old in step:
        seen = {old}
        new = step[old]
        while new in step and step[new] not in seen:
            seen.add(new)
            new = step[new]
        latest[old] = new
    return latest


def search(
    query: str,
    listings: Iterable[Listing],
    renames: Mapping[str, str],
    aliases: Mapping[str, str],
    limit: int = 10,
    prominent: Collection[str] = frozenset(),
) -> list[Match]:
    """Best first: exact symbol, a known short name or old symbol, the company's initials,
    symbol prefix, name prefix, a word in the name starting with it, then anywhere.
    Spaces and punctuation are ignored, so "tata steel" finds TATASTEEL and "l&t" finds LT.
    Within a step, `prominent` stocks (index members) come first.
    """
    q = key(query)
    if not q:
        return []
    by_symbol = {listing.symbol: listing for listing in listings}
    # An old symbol is shown as the company's current one.
    current = {old: new for old, new in renames.items() if new in by_symbol}
    named_alias = {alias: symbol for alias, symbol in aliases.items() if symbol in by_symbol} | {
        key(old): new for old, new in current.items()
    }

    ranked: list[tuple[int, int, int, str, Match]] = []
    for listing in by_symbol.values():
        if listing.symbol in current:
            continue
        symbol = key(listing.symbol)
        name = listing.name or ""
        words = re.findall(r"[A-Za-z0-9&]+", name)
        name_key = key(name)
        alias = None
        if symbol == q:
            tier = 0
        elif named_alias.get(q) == listing.symbol:
            tier, alias = 1, _alias_label(query, current, listing.symbol)
        elif q in initials(name):
            tier = 2
        elif symbol.startswith(q):
            tier = 3
        elif name_key.startswith(q):
            tier = 4
        elif any(key("".join(words[i:])).startswith(q) for i in range(1, len(words))):
            tier = 5
        elif q in symbol or q in name_key:
            tier = 6
        else:
            continue
        # Then stocks with a company name (old listings often have none).
        match = Match(listing.symbol, listing.name, listing.series, alias)
        ranked.append(
            (
                tier,
                0 if listing.symbol in prominent else 1,
                0 if listing.name else 1,
                listing.symbol,
                match,
            )
        )
    ranked.sort(key=lambda r: r[:4])
    return [r[4] for r in ranked[:limit]]


def _alias_label(query: str, current: Mapping[str, str], symbol: str) -> str:
    q = key(query)
    for old, new in current.items():
        if new == symbol and key(old) == q:
            return f"was {old}"
    return query.strip().upper()
