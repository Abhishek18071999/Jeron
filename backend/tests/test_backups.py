"""Is there a backup to come back to? (app/backups.py, backup/backup.sh)."""

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.backups import folder_status, read_check, status

NOW = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)
SYNCED = "D:/Google Drive/jeron-backups"


def _dump(name: str, hours_ago: float, size: int = 2**20) -> tuple[str, datetime, int]:
    return name, NOW - timedelta(hours=hours_ago), size


OK = read_check(
    "ok\tjeron-2026-10-24.dump\t2026-10-24T02:10:00+0530\n"
    "journal entries 12, fills 30, price rows 900000, signals 40\n"
)


def test_read_check() -> None:
    assert OK is not None and OK.ok and OK.dump == "jeron-2026-10-24.dump"
    assert OK.at == datetime(2026, 10, 23, 20, 40, tzinfo=UTC)
    assert OK.detail.startswith("journal entries 12")
    bad = read_check("failed\tjeron-2026-10-24.dump\t2026-10-24T02:10:00+0530\nend of file\n")
    assert bad is not None and not bad.ok and bad.detail == "end of file"
    assert read_check("") is None
    assert read_check("garbage") is None
    assert read_check("ok\tx\tnot a time").at is None  # type: ignore[union-attr]


def test_healthy_backups_have_no_problem() -> None:
    s = status(
        [_dump("jeron-2026-10-24.dump", 25), _dump("jeron-2026-10-25.dump", 1)], OK, NOW, SYNCED
    )
    assert s.problem is None and s.notes == []
    assert s.newest == "jeron-2026-10-25.dump" and s.count == 2 and s.size_bytes == 2 * 2**20


def test_stale_backup_is_a_problem_at_48_hours() -> None:
    assert status([_dump("jeron-2026-10-23.dump", 47.9)], OK, NOW, SYNCED).problem is None
    s = status([_dump("jeron-2026-10-22.dump", 72)], OK, NOW, SYNCED)
    assert s.problem is not None and "3 days old" in s.problem and "logs backup" in s.problem


def test_failed_restore_is_a_problem() -> None:
    failed = read_check("failed\tjeron-2026-10-25.dump\t2026-10-25T02:10:00+0530\nend of file\n")
    s = status([_dump("jeron-2026-10-25.dump", 1)], failed, NOW, SYNCED)
    assert s.problem is not None and "restore test" in s.problem and "end of file" in s.problem


def test_notes_for_a_local_folder_and_missing_or_old_restore_tests() -> None:
    s = status([_dump("jeron-2026-10-25.dump", 1)], None, NOW, "./backups")
    assert s.problem is None
    assert any("this computer only" in n for n in s.notes)
    assert any("No restore test yet" in n for n in s.notes)
    old = read_check("ok\tjeron-2026-10-10.dump\t2026-10-10T02:10:00+0530\n")
    s = status([_dump("jeron-2026-10-25.dump", 1)], old, NOW, SYNCED)
    assert s.problem is None and s.notes == ["The last restore test was 15 days ago."]


def test_no_backup_yet() -> None:
    s = status([], None, NOW, SYNCED)
    assert s.newest is None and s.problem is not None and "No backup" in s.problem


def test_folder_status_reads_the_files(tmp_path: Path) -> None:
    dump = tmp_path / "jeron-2026-10-25.dump"
    dump.write_bytes(b"x" * 100)
    stamp = (NOW - timedelta(hours=2)).timestamp()
    os.utime(dump, (stamp, stamp))
    (tmp_path / "other.txt").write_text("not a dump")
    (tmp_path / "restore-check.txt").write_text(
        "ok\tjeron-2026-10-25.dump\t2026-10-25T02:10:00+0000\njournal entries 1\n"
    )
    s = folder_status(tmp_path, NOW, SYNCED)
    assert s.newest == "jeron-2026-10-25.dump" and s.count == 1 and s.size_bytes == 100
    assert s.check is not None and s.check.ok and s.problem is None


def test_preopen_message_carries_the_backup_problem() -> None:
    from app.exits.job import PreOpen, preopen_message

    p = PreOpen(date(2026, 11, 2), date(2026, 10, 30), date(2026, 10, 30), [], 0, 0)
    assert "BACKUP" not in preopen_message(p)
    assert "BACKUP\n- The newest backup" in preopen_message(p, backup_note="The newest backup x")
