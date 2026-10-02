"""Reading NSE's ASM (Additional Surveillance Measure) list.

NSE publishes the ASM lists only on www.nseindia.com, which Jeron can't download
from, so the list is saved from NSE's ASM page as CSV and imported with
`python -m app.cli asm-import file.csv`. Any CSV with a symbol column works; a
stage column, if present, is kept.
"""

import csv
import io


def read_asm_csv(content: bytes) -> dict[str, str | None]:
    """Symbol -> stage (or None) from a CSV with a "Symbol" column."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    columns = {(c or "").strip().lower(): c for c in reader.fieldnames or []}
    symbol_col = next((columns[c] for c in columns if c in ("symbol", "nse symbol")), None)
    if symbol_col is None:
        raise ValueError(f"no Symbol column in the ASM file (columns: {list(columns)})")
    stage_col = next((columns[c] for c in columns if "stage" in c), None)
    out: dict[str, str | None] = {}
    for row in reader:
        symbol = (row.get(symbol_col) or "").strip().upper()
        if symbol and symbol != "-":
            stage = (row.get(stage_col) or "").strip() if stage_col else ""
            out[symbol] = stage or None
    return out
