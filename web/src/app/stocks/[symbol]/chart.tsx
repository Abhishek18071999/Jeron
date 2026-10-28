"use client";

import {
  type AutoscaleInfo,
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type SeriesMarkerBar,
  createChart,
  createSeriesMarkers,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import type { Candle } from "@/lib/api";
import { RANGES, type RangeKey, relativeStrength, sessionsFor } from "@/lib/chart";

export type Level = { price: number; title: string; color: string; dashed?: boolean };
// A dated event drawn under or over its bar: a signal, or one of my fills.
export type Marker = { time: string; kind: "signal" | "research" | "buy" | "sell"; text: string };

const UP = "#16a34a";
const DOWN = "#dc2626";

function palette(dark: boolean) {
  return {
    text: dark ? "#d4d4d4" : "#404040",
    grid: dark ? "#262626" : "#f0f0f0",
    volumeUp: dark ? "rgba(22,163,74,0.35)" : "rgba(22,163,74,0.3)",
    volumeDown: dark ? "rgba(220,38,38,0.35)" : "rgba(220,38,38,0.3)",
  };
}

const markerStyle: Record<Marker["kind"], Pick<SeriesMarkerBar<Time>, "position" | "color" | "shape">> = {
  signal: { position: "belowBar", color: "#2563eb", shape: "arrowUp" },
  research: { position: "belowBar", color: "#94a3b8", shape: "arrowUp" },
  buy: { position: "belowBar", color: UP, shape: "circle" },
  sell: { position: "aboveBar", color: DOWN, shape: "circle" },
};

const NO_MARKERS: Marker[] = [];

// Follow the system's light/dark setting while the page is open.
const darkQuery = () => window.matchMedia("(prefers-color-scheme: dark)");
function subscribeDark(onChange: () => void) {
  const media = darkQuery();
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

export function PriceChart({
  candles,
  levels,
  markers = NO_MARKERS,
}: {
  candles: Candle[];
  levels: Level[];
  markers?: Marker[];
}) {
  const box = useRef<HTMLDivElement>(null);
  const [range, setRange] = useState<RangeKey>("1Y");
  const dark = useSyncExternalStore(subscribeDark, () => darkQuery().matches, () => false);
  const hasIndex = candles.some((c) => c.nifty500 !== null && c.nifty500 !== undefined);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const colors = palette(dark);
    const chart = createChart(el, {
      height: hasIndex ? 520 : 420,
      autoSize: true,
      localization: { locale: "en-IN" },
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: colors.text,
        panes: { separatorColor: colors.grid },
      },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      timeScale: { borderVisible: false },
      rightPriceScale: { borderVisible: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      borderVisible: false,
      // Keep the signal's stop and targets on screen even when price is far from them.
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const info = original();
        if (!info?.priceRange || levels.length === 0) return info;
        const prices = levels.map((l) => l.price);
        return {
          ...info,
          priceRange: {
            minValue: Math.min(info.priceRange.minValue, ...prices),
            maxValue: Math.max(info.priceRange.maxValue, ...prices),
          },
        };
      },
    });
    series.setData(
      candles.map((c) => ({
        time: c.time as Time,
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
      })),
    );

    // Volume along the bottom of the price pane, on its own scale.
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(
      candles.map((c) => ({
        time: c.time as Time,
        value: c.volume,
        color: Number(c.close) >= Number(c.open) ? colors.volumeUp : colors.volumeDown,
      })),
    );

    for (const [key, color] of [
      ["ema50", "#2563eb"],
      ["ema200", "#a855f7"],
    ] as const) {
      const line = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        title: key.toUpperCase(),
      });
      line.setData(
        candles
          .filter((c) => c[key] !== null)
          .map((c) => ({ time: c.time as Time, value: c[key] as number })),
      );
    }
    for (const level of levels) {
      series.createPriceLine({
        price: level.price,
        color: level.color,
        lineWidth: 1,
        lineStyle: level.dashed ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true,
        title: level.title,
      });
    }
    const times = new Set(candles.map((c) => c.time));
    createSeriesMarkers(
      series,
      markers
        .filter((m) => times.has(m.time))
        .sort((a, b) => a.time.localeCompare(b.time))
        .map((m) => ({ time: m.time as Time, text: m.text, ...markerStyle[m.kind] })),
    );

    // Second pane: the stock against the Nifty 500, 100 at the first bar shown.
    if (hasIndex) {
      const rs = chart.addSeries(
        LineSeries,
        { color: "#f59e0b", lineWidth: 2, priceLineVisible: false, title: "vs Nifty 500" },
        1,
      );
      // Rebased to 100 where the chosen range starts: the line says how the stock did
      // against the index over exactly the bars on screen.
      const from = candles.length - sessionsFor(range, candles.length);
      rs.setData(relativeStrength(candles, from).map((p) => ({ time: p.time as Time, value: p.value })));
      rs.createPriceLine({
        price: 100,
        color: colors.text,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: false,
        title: "",
      });
      chart.panes()[1]?.setHeight(110);
    }

    const shown = sessionsFor(range, candles.length);
    chart.timeScale().setVisibleLogicalRange({ from: candles.length - shown - 0.5, to: candles.length - 0.5 });
    return () => {
      chart.remove();
    };
  }, [candles, levels, markers, dark, hasIndex, range]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-1" role="group" aria-label="Chart range">
        {RANGES.map((r) => (
          <button
            key={r.key}
            type="button"
            onClick={() => setRange(r.key)}
            aria-pressed={range === r.key}
            className={`rounded-md px-2 py-0.5 text-xs font-medium ${range === r.key ? "bg-accent text-accent-fg" : "text-muted hover:bg-surface-2"}`}
          >
            {r.key}
          </button>
        ))}
      </div>
      <div ref={box} className={hasIndex ? "h-[520px] w-full" : "h-[420px] w-full"} />
    </div>
  );
}
