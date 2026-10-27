"""Gets a new install going, and keeps it going, without commands. The scheduler runs
`tick` on start and every few minutes; the Setup page shows `status`.

Two lanes, so a long import never holds up the daily run:

- the market lane (shared with the scheduler's daily, pre-open and weekly jobs): the
  price history when there is none (`backfill`), the first `daily`, announcements for
  days whose PR bundle is stored but whose `an` file was never read (`events`, from the
  cache), the news labeller's last 30 days once a day when its key is set, a backtest of
  every strategy version that has none (and of quality-trend after new results, and once
  more of a paper-traded version whose newest run has no evidence rating), then
  `paper`;
- the imports lane: each file in the imports folder (the `imports` folder next to
  docker-compose.yml, or uploaded on the Setup page) is recognised by its columns and
  imported with its CLI command, then moved to `imports/done` or `imports/failed` with
  the command's output beside it. A .zip is unpacked first. When no quarterly results
  are loaded, the results lists bundled in `seed/` are queued once.

Every step is a CLI command run as its own process, so it does exactly what the command
does, and its output is kept in a log the Setup page shows.
"""

import csv
import io
import json
import logging
import shutil
import subprocess
import sys
import threading
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtest.confidence import CONFIDENCE_VERSION
from app.backtest.strategies import COMBINED, STRATEGIES
from app.config import get_settings
from app.data import store
from app.data.deals import is_insider_file
from app.data.pipeline import ANNOUNCEMENTS_SOURCE
from app.models import BacktestRun, DailyBar, PaperAccount, ScanRun, SourceFile
from app.signals.build import IST

log = logging.getLogger("jeron.autopilot")

SEED = Path(__file__).resolve().parent.parent / "seed" / "nse-results-2016-2026.zip"
IMPORTABLE = (".csv", ".json", ".zip")
NEWS_BACKLOG_DAYS = 30
LOG_TAIL = 12

# The market lane. The scheduler's jobs take it too, so nothing writes prices twice.
market_lock = threading.Lock()
_imports_lock = threading.Lock()
_state_lock = threading.Lock()

Runner = Callable[[Sequence[str], Path], int]


class UnknownFileError(ValueError):
    pass


# State -----------------------------------------------------------------------------


def _state_path() -> Path:
    return Path(get_settings().data_dir) / "autopilot.json"


def load_state() -> dict[str, Any]:
    try:
        data = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _update(**changes: Any) -> dict[str, Any]:
    with _state_lock:
        state = load_state()
        for key, value in changes.items():
            if value is None:
                state.pop(key, None)
            else:
                state[key] = value
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, default=str))
        tmp.replace(path)
        return state


def _now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def _logs_dir() -> Path:
    return Path(get_settings().data_dir) / "autopilot-logs"


def run_cli(args: Sequence[str], log_file: Path) -> int:
    """`python -m app.cli ARGS` as its own process, its output in `log_file`."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as out:
        out.write(f"$ python -m app.cli {' '.join(args)}\n")
        out.flush()
        done = subprocess.run(
            [sys.executable, "-u", "-m", "app.cli", *args],
            stdout=out,
            stderr=subprocess.STDOUT,
            check=False,
        )
        out.write(f"(exit code {done.returncode})\n")
    return done.returncode


def tail(path: Path, lines: int = LOG_TAIL) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [line for line in text.splitlines() if line.strip()][-lines:]


# The imports lane -------------------------------------------------------------------


def imports_dir() -> Path:
    return Path(get_settings().imports_dir)


def pending(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in IMPORTABLE
    )


def classify(path: Path) -> tuple[str, list[str]]:
    """What the file is and the CLI command that imports it, from its columns."""
    content = path.read_bytes()
    text = content.decode("utf-8-sig", errors="replace")
    name = path.name.lower()
    if text.lstrip()[:1] in ("[", "{"):
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise UnknownFileError(f"not valid JSON ({exc})") from exc
        rows = data.get("data", []) if isinstance(data, dict) else data
        first = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
        headers = [str(k) for k in first]
    else:
        headers = next(csv.reader(io.StringIO(text)), [])
    keys = {h.strip().strip("*").strip().lower() for h in headers}
    joined = " ".join(keys)
    if "company name" in keys and "xbrl" in joined:
        return "quarterly results", ["fundamentals-import", str(path)]
    if is_insider_file(headers):
        return "insider trades", ["deals-import", str(path)]
    if "block" in name or "bulk" in name:
        return "bulk/block deals", ["deals-import", str(path)]
    if "trade_id" in keys and "trade_date" in keys:
        return "Zerodha tradebook", ["tradebook", str(path)]
    if "purpose" in keys or "bm_purpose" in keys:
        return "board meetings", ["events-import", str(path)]
    if "asm" in name and ("symbol" in keys or "nse symbol" in keys):
        return "ASM list", ["asm-import", str(path)]
    raise UnknownFileError(
        "Jeron doesn't recognise this file. It reads NSE's Financial Results CSV, the bulk "
        "or block deals and insider-trading CSVs, the board-meetings CSV, the ASM list "
        "(with ASM in its name) and Zerodha's tradebook CSV."
    )


def _unpack(path: Path) -> list[str]:
    """Moves a zip's CSV and JSON files into its folder; returns their names."""
    out = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = Path(info.filename).name  # never a path outside the folder
            if info.is_dir() or not name or name.startswith(".") or "__MACOSX" in info.filename:
                continue
            if Path(name).suffix.lower() not in (".csv", ".json"):
                continue
            target = path.parent / name
            with z.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            out.append(name)
    return out


def _stamp() -> str:
    return datetime.now(IST).strftime("%Y%m%d-%H%M%S")


def _settle(path: Path, outcome: str, log_file: Path) -> None:
    folder = path.parent / outcome
    folder.mkdir(exist_ok=True)
    target = folder / path.name
    if target.exists():
        target = folder / f"{_stamp()}-{path.name}"
    shutil.move(str(path), target)
    shutil.move(str(log_file), target.with_name(target.name + ".log"))


def import_one(path: Path, run: Runner = run_cli) -> str:
    """Imports one file and files it under done/ or failed/. Returns the outcome."""
    working = path.parent / ".working"
    working.mkdir(exist_ok=True)
    log_file = working / f"{path.name}.log"
    log_file.unlink(missing_ok=True)
    if path.suffix.lower() == ".zip":
        try:
            names = _unpack(path)
        except zipfile.BadZipFile as exc:
            log_file.write_text(f"Not a readable zip file: {exc}\n")
            _settle(path, "failed", log_file)
            return "failed"
        log_file.write_text(f"Unpacked {len(names)} files: {', '.join(names) or 'none'}\n")
        _settle(path, "done", log_file)
        return "unpacked"
    try:
        kind, args = classify(path)
    except (UnknownFileError, OSError) as exc:
        log_file.write_text(f"{exc}\n")
        _settle(path, "failed", log_file)
        return "failed"
    moved = working / path.name
    shutil.move(str(path), moved)
    _update(importing={"file": path.name, "kind": kind, "since": _now()})
    log_file.write_text(f"Importing {path.name} as {kind}.\n")
    args = [str(moved) if a == str(path) else a for a in args]
    try:
        code = run(args, log_file)
    finally:
        _update(importing=None)
    target = path.parent / path.name
    shutil.move(str(moved), target)
    outcome = "done" if code == 0 else "failed"
    _settle(target, outcome, log_file)
    if code == 0 and kind == "quarterly results":
        _update(results_changed=True)
    return outcome


def resume_interrupted(folder: Path) -> None:
    """A file left in .working by a stop goes back in the queue (imports are re-runnable)."""
    working = folder / ".working"
    if not working.is_dir():
        return
    for p in working.iterdir():
        if p.suffix == ".log":
            p.unlink(missing_ok=True)
        elif p.is_file():
            shutil.move(str(p), folder / p.name)


def seed_results(session: Session, folder: Path) -> bool:
    """Queues the bundled results lists once, when no results are loaded."""
    from app.fundamentals.job import results_loaded

    if load_state().get("seeded") or not SEED.exists() or results_loaded(session):
        return False
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(SEED, folder / SEED.name)
    _update(seeded=_now())
    return True


def process_imports(folder: Path | None = None, run: Runner = run_cli) -> list[str]:
    """Imports everything waiting, oldest name first; unpacked zips add to the queue."""
    folder = folder or imports_dir()
    if not _imports_lock.acquire(blocking=False):
        return []
    try:
        outcomes = []
        while files := pending(folder):
            outcomes.append(f"{files[0].name}: {import_one(files[0], run)}")
        return outcomes
    finally:
        _imports_lock.release()


# The market lane --------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    name: str
    why: str
    args: list[str]


def announcement_gap(session: Session, after: date | None) -> tuple[date, date] | None:
    """The first and last day whose PR bundle is stored but whose announcements were
    never read (after `after`)."""
    read = select(SourceFile.trade_date).where(SourceFile.source == ANNOUNCEMENTS_SOURCE)
    stmt = select(func.min(SourceFile.trade_date), func.max(SourceFile.trade_date)).where(
        SourceFile.source == store.NSE_PR,
        SourceFile.status == "ok",
        SourceFile.trade_date.not_in(read),
    )
    if after:
        stmt = stmt.where(SourceFile.trade_date > after)
    first, last = session.execute(stmt).one()
    return (first, last) if first else None


def untested(session: Session) -> list[str]:
    """Strategy keys whose current version has no backtest run."""
    done = set(session.scalars(select(BacktestRun.strategy_version).distinct()))
    every = {k: s.version for k, s in STRATEGIES.items()}
    every.update({k: c.version for k, c in COMBINED.items()})
    return [k for k, version in every.items() if version not in done]


def unrated(session: Session) -> list[str]:
    """Strategy keys with an active paper account whose newest run has no evidence
    rating (made before the confidence engine, decision 0018): backtested once more so
    their status shows how strong the evidence is."""
    active = set(
        session.scalars(
            select(PaperAccount.strategy_version).where(PaperAccount.status == "active")
        )
    )
    newest = dict(
        session.execute(
            select(BacktestRun.strategy_version, func.max(BacktestRun.id)).group_by(
                BacktestRun.strategy_version
            )
        ).all()
    )
    out = []
    for key, strategy in STRATEGIES.items():
        run_id = newest.get(strategy.version)
        if strategy.version not in active or run_id is None:
            continue
        run = session.get(BacktestRun, run_id)
        if run is not None and "confidence" not in run.summary:
            out.append(key)
    return out


def _inputs_signature(session: Session) -> str:
    from app.fundamentals.job import results_loaded

    return f"results={results_loaded(session)} meetings={store.board_meetings_loaded(session)}"


def next_step(session: Session, today: date, news_on: bool) -> Step | None:
    state = load_state()
    if session.scalar(select(DailyBar.trade_date).limit(1)) is None:
        return Step("backfill", "No price history yet: downloading NSE's since 2016.", ["backfill"])
    if session.scalar(select(ScanRun.id).limit(1)) is None:
        return Step("daily", "History stored: the first daily run (scan, paper).", ["daily"])
    checked = state.get("announcements_checked_to")
    gap = announcement_gap(session, date.fromisoformat(checked) if checked else None)
    if gap:
        return Step(
            "events",
            f"Reading company announcements and board meetings for {gap[0]} to {gap[1]} "
            "from the stored NSE files.",
            ["events", "--start", gap[0].isoformat(), "--end", gap[1].isoformat()],
        )
    if news_on and state.get("news_backlog") != today.isoformat():
        start = today - timedelta(days=NEWS_BACKLOG_DAYS)
        return Step(
            "news",
            f"Labelling the last {NEWS_BACKLOG_DAYS} days' announcements.",
            ["news-label", "--start", start.isoformat()],
        )
    tried = state.get("backtests_tried", {})
    signature = _inputs_signature(session)
    keys = [k for k in untested(session) if tried.get(k) != signature]
    rated = state.get("rated", {})
    keys += [k for k in unrated(session) if rated.get(k) != CONFIDENCE_VERSION and k not in keys]
    if state.get("results_changed") and "quality-trend" not in keys:
        keys.append("quality-trend")
    if state.get("importing") or pending(imports_dir()):
        # Results are still coming in: test the strategy that reads them once they're all in.
        keys = [k for k in keys if k != "quality-trend"]
    if keys:
        args = ["backtest"]
        for k in keys:
            args += ["--strategy", k]
        return Step("backtest", f"Backtesting {', '.join(keys)}.", args)
    if state.get("paper_due"):
        return Step("paper", "Opening paper accounts for the new backtests.", ["paper"])
    return None


def _finish(step: Step, session: Session, code: int, today: date) -> None:
    if step.name == "events":
        last = step.args[step.args.index("--end") + 1]
        _update(announcements_checked_to=last)
    elif step.name == "news":
        _update(news_backlog=today.isoformat())
    elif step.name == "backtest":
        keys = [step.args[i + 1] for i, a in enumerate(step.args) if a == "--strategy"]
        tried = load_state().get("backtests_tried", {})
        signature = _inputs_signature(session)
        tried.update({k: signature for k in keys})
        rated = load_state().get("rated", {})
        rated.update({k: CONFIDENCE_VERSION for k in keys})
        _update(backtests_tried=tried, rated=rated, results_changed=None, paper_due=True)
    elif step.name == "paper":
        _update(paper_due=None)


def run_market_step(
    session_factory: Callable[[], Session], run: Runner = run_cli, today: date | None = None
) -> str | None:
    """Runs the first setup step that is due, if the market lane is free."""
    from app.news.job import make_labeller

    if not market_lock.acquire(blocking=False):
        return None
    try:
        day = today or datetime.now(IST).date()
        with session_factory() as session:
            step = next_step(session, day, make_labeller(get_settings()) is not None)
        if step is None:
            return None
        log_file = _logs_dir() / f"{step.name}.log"
        log_file.unlink(missing_ok=True)
        _update(now={"step": step.name, "why": step.why, "since": _now()})
        log.info("Autopilot: %s", step.why)
        try:
            code = run(step.args, log_file)
        finally:
            _update(now=None)
        with session_factory() as session:
            _finish(step, session, code, day)
        _update(last={"step": step.name, "why": step.why, "code": code, "at": _now()})
        return step.name
    finally:
        market_lock.release()


def tick(session_factory: Callable[[], Session]) -> None:
    """One round: queue the seed if needed, start the imports lane, run a market step."""
    folder = imports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with session_factory() as session:
        seed_results(session, folder)
    if pending(folder):
        threading.Thread(target=process_imports, args=(folder,), daemon=True).start()
    run_market_step(session_factory)


def start() -> None:
    """On the scheduler's start: nothing is running yet, so clear what a stop left."""
    resume_interrupted(imports_dir())
    _update(now=None, importing=None)


# What the Setup page shows ----------------------------------------------------------


def imports_status(folder: Path | None = None, recent: int = 15) -> dict[str, Any]:
    folder = folder or imports_dir()
    state = load_state()
    importing = state.get("importing")
    running = None
    if importing:
        running = {**importing, "log": tail(folder / ".working" / f"{importing['file']}.log")}
    finished = []
    for outcome in ("done", "failed"):
        sub = folder / outcome
        if not sub.is_dir():
            continue
        for log_file in sub.glob("*.log"):
            finished.append(
                {
                    "file": log_file.name.removesuffix(".log"),
                    "outcome": outcome,
                    "at": datetime.fromtimestamp(log_file.stat().st_mtime, IST).isoformat(
                        timespec="seconds"
                    ),
                    "log": tail(log_file, 4),
                }
            )
    finished.sort(key=lambda f: f["at"], reverse=True)
    return {
        "pending": [p.name for p in pending(folder)],
        "running": running,
        "finished": finished[:recent],
    }


def market_status() -> dict[str, Any]:
    state = load_state()
    now = state.get("now")
    if now:
        now = {**now, "log": tail(_logs_dir() / f"{now['step']}.log")}
    last = state.get("last")
    if last:
        last = {**last, "log": tail(_logs_dir() / f"{last['step']}.log", 4)}
    return {"now": now, "last": last}
