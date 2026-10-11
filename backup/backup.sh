#!/bin/sh
# Nightly database backup (spec section 10), run by the `backup` service in
# docker-compose.yml. Once a day, after BACKUP_TIME (IST), it writes
# jeron-YYYY-MM-DD.dump (pg_dump custom format) to /backups and keeps the newest
# BACKUP_KEEP. If the machine was off at that time, the backup runs when it is back.
#
#   sh /backup.sh       the daily loop (what the service runs)
#   sh /backup.sh now   one backup now, then exit
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
    if pg_dump --format=custom --file="$DIR/.partial.dump"; then
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

echo "backup: daily after $AT ($(date +%Z)), keeping $KEEP, in $DIR"
while true; do
    if [ ! -f "$DIR/jeron-$(date +%Y-%m-%d).dump" ] &&
        [ "$(minutes "$(date +%H:%M)")" -ge "$(minutes "$AT")" ]; then
        backup || true
    fi
    sleep 300
done
