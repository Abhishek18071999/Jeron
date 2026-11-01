set -x
L=$SCRATCH
cd $REPO/backend
export JERON_DATABASE_URL=postgresql+psycopg://jeron:jeron@localhost:5432/jeron
while pgrep -f "app.cli backfill" >/dev/null; do sleep 30; done
uv run python -m app.cli backfill --start 2016-01-01 > $L/backfill2.log 2>&1
uv run python -m app.cli lists --start 2016-01-01 > $L/lists.log 2>&1
uv run python -m app.cli lists --start 2016-01-01 >> $L/lists.log 2>&1
uv run python -m app.cli events --start 2016-01-01 > $L/events.log 2>&1
uv run python -m app.cli quality --start 2016-01-01 > $L/quality.log 2>&1
uv run python -m app.cli fundamentals-import $L/seed/*.csv > $L/fund.log 2>&1
echo PIPELINE DONE
