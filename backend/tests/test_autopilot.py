"""The autopilot's imports lane without a database: files recognised by their columns,
zips unpacked safely, each file filed under done/ or failed/ with its output."""

import io
import zipfile
from pathlib import Path

import pytest

from app import autopilot
from app.backtest.job import missing_inputs
from app.backtest.strategies import QUALITY_TREND, SCORE_SWING
from tests.backtest_helpers import one_stock_market

RESULTS = (
    '"COMPANY NAME","AUDITED / UNAUDITED","CUMULATIVE / NON-CUMULATIVE",'
    '"CONSOLIDATED / NON-CONSOLIDATED","IND AS/ NON IND AS","PERIOD","PERIOD ENDED",'
    '"RELATING TO","** XBRL","Exchange Received Time","Exchange Dissemination Time",'
    '"Time Taken"\n'
)


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("JERON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JERON_IMPORTS_DIR", str(tmp_path / "imports"))
    autopilot.get_settings.cache_clear()
    out = tmp_path / "imports"
    out.mkdir()
    yield out
    autopilot.get_settings.cache_clear()


def _write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8-sig")
    return path


def test_files_are_recognised_by_their_columns(folder):
    cases = {
        "CF-FR-equities-01-01-2025.csv": (RESULTS, "quarterly results", "fundamentals-import"),
        "CF-Insider-Trading.csv": (
            "SYMBOL,COMPANY,NAME OF THE ACQUIRER/DISPOSER,CATEGORY OF PERSON\n",
            "insider trades",
            "deals-import",
        ),
        "Bulk-Deals-01-01-2025.csv": (
            "Date,Symbol,Client Name,Buy/Sell\n", "bulk/block deals", "deals-import"
        ),
        "tradebook-AB1234-EQ.csv": (
            "symbol,isin,trade_date,exchange,segment,series,trade_type,quantity,price,trade_id\n",
            "Zerodha tradebook",
            "tradebook",
        ),
        "board-meetings.csv": (
            "SYMBOL,COMPANY NAME,PURPOSE,MEETING DATE\n", "board meetings", "events-import"
        ),
        "asm-list.csv": ("Sr No,Symbol,Security Name,Stage\n", "ASM list", "asm-import"),
    }  # fmt: skip
    for name, (text, kind, command) in cases.items():
        found, args = autopilot.classify(_write(folder, name, text))
        assert (found, args[0]) == (kind, command), name
        assert args[1].endswith(name)
    with pytest.raises(autopilot.UnknownFileError):
        autopilot.classify(_write(folder, "holiday-photos.csv", "a,b,c\n"))


def test_an_import_is_filed_with_its_output(folder):
    _write(folder, "results.csv", RESULTS)
    _write(folder, "nonsense.csv", "a,b\n")
    ran: list[list[str]] = []

    def run(args, log_file):
        ran.append(list(args))
        assert Path(args[1]).exists()  # moved to .working while it runs
        with log_file.open("a") as out:
            out.write("1 filings listed\n")
        return 0

    outcomes = autopilot.process_imports(folder, run)
    assert outcomes == ["nonsense.csv: failed", "results.csv: done"]
    assert ran[0][0] == "fundamentals-import"
    assert (folder / "done" / "results.csv").exists()
    assert "1 filings listed" in (folder / "done" / "results.csv.log").read_text()
    assert "doesn't recognise" in (folder / "failed" / "nonsense.csv.log").read_text()
    assert autopilot.load_state()["results_changed"] is True
    status = autopilot.imports_status(folder)
    assert status["pending"] == [] and status["running"] is None
    assert {f["file"]: f["outcome"] for f in status["finished"]} == {
        "results.csv": "done",
        "nonsense.csv": "failed",
    }


def test_a_failed_command_goes_to_failed_and_a_second_copy_keeps_both(folder):
    for _ in range(2):
        _write(folder, "results.csv", RESULTS)
        autopilot.process_imports(folder, lambda args, log_file: 1)
    assert len(list((folder / "failed").glob("*results.csv"))) == 2
    assert "results_changed" not in autopilot.load_state()


def test_a_zip_is_unpacked_without_leaving_the_folder(folder):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("2016/nse-results-2016.csv", RESULTS)
        z.writestr("../../evil.csv", RESULTS)
        z.writestr("readme.txt", "hello")
        z.writestr("__MACOSX/._nse-results-2016.csv", "junk")
    (folder / "results.zip").write_bytes(data.getvalue())
    imported: list[str] = []

    def run(args, log_file):
        imported.append(Path(args[1]).name)
        return 0

    autopilot.process_imports(folder, run)
    assert sorted(imported) == ["evil.csv", "nse-results-2016.csv"]
    assert not (folder.parent / "evil.csv").exists()
    assert (folder / "done" / "results.zip").exists()


def test_an_import_stopped_halfway_is_queued_again(folder):
    working = folder / ".working"
    working.mkdir()
    (working / "results.csv").write_text(RESULTS)
    (working / "results.csv.log").write_text("half done")
    autopilot.resume_interrupted(folder)
    assert [p.name for p in autopilot.pending(folder)] == ["results.csv"]
    assert not (working / "results.csv.log").exists()


def test_strategies_missing_inputs_are_named_not_crashed():
    market = one_stock_market([(100.0, 101.0, 99.0, 100.0)] * 5)
    assert missing_inputs(market, SCORE_SWING) is None
    assert "fundamentals-import" in (missing_inputs(market, QUALITY_TREND) or "")
