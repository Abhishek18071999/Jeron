#!/bin/sh
# Nightly database backup (spec section 10), run by the `backup` service in
# docker-compose.yml. Once a day, after BACKUP_TIME (IST), it writes
# jeron-YYYY-MM-DD.dump (pg_dump custom format) to /backups and keeps the newest
# BACKUP_KEEP. If the machine was off at that time, the backup runs when it is back.
# A dump is kept only if pg_restore can read it. Once a week the newest dump is restored
# into a scratch database (jeron_restore_check, dropped after) and its tables counted;
# the result goes to restore-check.txt, which the Setup page and the pre-open check read.
#
#   sh /backup.sh          the daily loop (what the service runs)
#   sh /backup.sh now      one backup now, then exit
#   sh /backup.sh verify   restore the newest backup into a scratch database, then exit
#
# Restore (replaces what is in the database):
#   docker compose exec -T db pg_restore -U jeron -d jeron --clean --if-exists \
#     < backups/jeron-YYYY-MM-DD.dump
set -u

DIR="${BACKUP_DIR:-/backups}"
AT="${BACKUP_TIME:-02:00}"
KEEP="${BACKUP_KEEP:-14}"

backup() {
    name="jeron-$(date +%Y-%m-%d).dump"
    if pg_dump --format=custom --file="$DIR/.partial.dump" &&
        pg_restore --list "$DIR/.partial.dump" >/dev/null; then
        mv "$DIR/.partial.dump" "$DIR/$name"
        echo "backup: wrote $name ($(du -h "$DIR/$name" | cut -f1))"
    else
        rm -f "$DIR/.partial.dump"
        echo "backup: pg_dump failed; trying again in 5 minutes" >&2
        return 1
    fi
    # Keep the newest $KEEP.
    ls -1t "$DIR"/jeron-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
}

CHECK_DB=jeron_restore_check

stamp() { date +%Y-%m-%dT%H:%M:%S%z; }

# restore-check.txt: "ok|failed<TAB>dump<TAB>time" on the first line, what was found on
# the second.
verify() {
    newest=$(ls -1t "$DIR"/jeron-*.dump 2>/dev/null | head -n 1)
    if [ -z "$newest" ]; then
        printf 'failed\t-\t%s\nno backup to restore\n' "$(stamp)" >"$DIR/restore-check.txt"
        echo "backup: no backup to restore" >&2
        return 1
    fi
    name=$(basename "$newest")
    dropdb --if-exists "$CHECK_DB" 2>/dev/null && createdb "$CHECK_DB" || {
        printf 'failed\t%s\t%s\ncould not make the scratch database\n' "$name" "$(stamp)" \
            >"$DIR/restore-check.txt"
        return 1
    }
    if pg_restore --no-owner --exit-on-error --dbname="$CHECK_DB" "$newest" 2>"$DIR/.restore.log"; then
        counts=$(psql --dbname="$CHECK_DB" -tA -F ' ' -c "select
            (select count(*) from journal_entries), (select count(*) from journal_fills),
            (select count(*) from daily_bars), (select count(*) from signals)")
        set -- $counts
        printf 'ok\t%s\t%s\njournal entries %s, fills %s, price rows %s, signals %s\n' \
            "$name" "$(stamp)" "$1" "$2" "$3" "$4" >"$DIR/restore-check.txt"
        echo "backup: restored $name into $CHECK_DB: journal entries $1, fills $2, price rows $3"
        status=0
    else
        printf 'failed\t%s\t%s\n%s\n' "$name" "$(stamp)" "$(tail -n 1 "$DIR/.restore.log")" \
            >"$DIR/restore-check.txt"
        echo "backup: restoring $name failed: $(tail -n 1 "$DIR/.restore.log")" >&2
        status=1
    fi
    rm -f "$DIR/.restore.log"
    dropdb --if-exists "$CHECK_DB"
    return $status
}

# True when the last restore check is under a week old.
verified_lately() {
    [ -n "$(find "$DIR/restore-check.txt" -mtime -7 2>/dev/null)" ]
}

minutes() { # HH:MM -> minutes after midnight
    h=$(echo "$1" | cut -d: -f1 | sed 's/^0//')
    m=$(echo "$1" | cut -d: -f2 | sed 's/^0//')
    echo $(( ${h:-0} * 60 + ${m:-0} ))
}

mkdir -p "$DIR"
if [ "${1:-}" = "now" ]; then
    backup
    exit $?
fi
if [ "${1:-}" = "verify" ]; then
    verify
    exit $?
fi

echo "backup: daily after $AT ($(date +%Z)), keeping $KEEP, in $DIR"
while true; do
    if [ ! -f "$DIR/jeron-$(date +%Y-%m-%d).dump" ] &&
        [ "$(minutes "$(date +%H:%M)")" -ge "$(minutes "$AT")" ]; then
        backup && { verified_lately || verify || true; }
    fi
    sleep 300
done
