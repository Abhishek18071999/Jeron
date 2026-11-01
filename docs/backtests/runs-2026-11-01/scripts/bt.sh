L=$SCRATCH
cd $REPO/backend
export JERON_DATABASE_URL=postgresql+psycopg://jeron:jeron@localhost:5432/jeron
uv run python -m app.cli backtest --strategy rs-pullback --strategy fip-momentum --strategy momentum --strategy results-drift --strategy reversal --strategy top-score --strategy sector-rotation > $L/bt1.log 2>&1
echo "BT1 EXIT $?" >> $L/bt1.log
uv run python -m app.cli backtest --strategy combined-book > $L/bt2.log 2>&1
echo "BT2 EXIT $?" >> $L/bt2.log
