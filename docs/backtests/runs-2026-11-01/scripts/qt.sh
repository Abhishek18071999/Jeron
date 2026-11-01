L=$SCRATCH
cd $REPO/backend
export JERON_DATABASE_URL=postgresql+psycopg://jeron:jeron@localhost:5432/jeron
while ! grep -q "PIPELINE DONE" $L/pipeline.log; do sleep 60; done
uv run python -m app.cli backtest --strategy quality-trend > $L/qt.log 2>&1
echo "QT EXIT $?" >> $L/qt.log
