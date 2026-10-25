"""Is there a backup to come back to? (backup/backup.sh, run by the `backup` service.)

The backup service writes jeron-YYYY-MM-DD.dump every night and, once a week, restores
the newest into a scratch database and writes the result to restore-check.txt. This
reads that folder (mounted read only at `JERON_BACKUPS_MOUNT`) for the Setup page and
the pre-open check. A journal of real trades can't be downloaded again, so a backup
that stopped, or that can't be restored, is said out loud.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Nightly backups: older than this and the service has stopped or is failing.
STALE_AFTER = timedelta(hours=48)
# Restore checks run weekly; a few days' grace for a computer that was off.
CHECK_STALE_AFTER = timedelta(days=10)
# The default folder, on the same disk as the database.
LOCAL_DIRS = frozenset({"", "./backups", "backups", "./backups/"})
LOGS = "`docker compose logs backup`"


@dataclass(frozen=True)
class RestoreCheck:
    ok: bool
    dump: str
    at: datetime | None
    detail: str


@dataclass(frozen=True)
class BackupStatus:
    newest: str | None
    newest_at: datetime | None
    count: int
    size_bytes: int
    check: RestoreCheck | None
    problem: str | None  # something to fix; None when backups are healthy
    notes: list[str]


def read_check(text: str) -> RestoreCheck | None:
    """restore-check.txt: "ok|failed<TAB>dump<TAB>time" then a line of detail."""
    lines = text.splitlines()
    if not lines:
        return None
    parts = lines[0].split("\t")
    if len(parts) < 3 or parts[0] not in ("ok", "failed"):
        return None
    try:
        at: datetime | None = datetime.strptime(parts[2].strip(), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        at = None
    return RestoreCheck(parts[0] == "ok", parts[1], at, lines[1].strip() if len(lines) > 1 else "")


def _age(delta: timedelta) -> str:
    hours = int(delta.total_seconds() // 3600)
    if hours < 48:
        return f"{max(hours, 0)} hours"
    return f"{hours // 24} days"


def status(
    dumps: list[tuple[str, datetime, int]],
    check: RestoreCheck | None,
    now: datetime,
    host_dir: str = "",
) -> BackupStatus:
    """`dumps` are (name, modified, bytes) of jeron-*.dump files. Pure."""
    notes: list[str] = []
    if host_dir.strip() in LOCAL_DIRS:
        notes.append(
            "The backups are on this computer only: if its disk fails, the journal goes "
            "with it. Set JERON_BACKUP_DIR in .env to a synced folder (Google Drive, "
            "OneDrive) and run `docker compose up -d`."
        )
    if not dumps:
        return BackupStatus(
            None,
            None,
            0,
            0,
            check,
            f"No backup has been written yet. Check that the backup service runs: {LOGS}.",
            notes,
        )
    name, at, size = max(dumps, key=lambda d: d[1])
    total = sum(d[2] for d in dumps)
    problem = None
    if now - at > STALE_AFTER:
        problem = (
            f"The newest backup ({name}) is {_age(now - at)} old: the backup service has "
            f"stopped or is failing. See {LOGS}."
        )
    elif check is not None and not check.ok:
        problem = (
            f"The last restore test of {check.dump} failed ({check.detail or 'no detail'}). "
            f"Run `docker compose exec backup sh /backup.sh verify` and see {LOGS}."
        )
    if check is None:
        notes.append("No restore test yet: the backup service runs one a week.")
    elif check.ok and check.at is not None and now - check.at > CHECK_STALE_AFTER:
        notes.append(f"The last restore test was {_age(now - check.at)} ago.")
    return BackupStatus(name, at, len(dumps), total, check, problem, notes)


def folder_status(folder: Path, now: datetime | None = None, host_dir: str = "") -> BackupStatus:
    """The status of the backups in `folder`."""
    now = now or datetime.now(UTC)
    dumps = []
    for path in folder.glob("jeron-*.dump"):
        stat = path.stat()
        dumps.append((path.name, datetime.fromtimestamp(stat.st_mtime, UTC), stat.st_size))
    check_file = folder / "restore-check.txt"
    check = read_check(check_file.read_text(errors="replace")) if check_file.is_file() else None
    return status(dumps, check, now, host_dir)


def configured_status(
    mount: str, host_dir: str, now: datetime | None = None
) -> BackupStatus | None:
    """The status from the settings, or None when the folder isn't mounted here (a
    backend run outside Docker Compose)."""
    if not mount or not Path(mount).is_dir():
        return None
    return folder_status(Path(mount), now, host_dir)
