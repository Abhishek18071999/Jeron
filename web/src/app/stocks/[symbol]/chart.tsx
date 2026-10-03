"use client";

import {
  type AutoscaleInfo,
  CandlestickSeries,
  ColorType,
  LineSeries,
  LineStyle,
  createChart,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { Candle } from "@/lib/api";

export type Level = { price: number; title: string; color: string; dashed?: boolean };

export function PriceChart({ candles, levels }: { candles: Candle[]; levels: Level[] }) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const chart = createChart(el, {
      height: 420,
      autoSize: true,
      localization: { locale: "en-IN" },
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: dark ? "#d4d4d4" : "#404040",
      },
      grid: {
        vertLines: { color: dark ? "#262626" : "#f0f0f0" },
        horzLines: { color: dark ? "#262626" : "#f0f0f0" },
      },
      timeScale: { borderVisible: false },
      rightPriceScale: { borderVisible: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#16a34a",
      downColor: "#dc2626",
      wickUpColor: "#16a34a",
      wickDownColor: "#dc2626",
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
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [candles, levels]);

  return <div ref={box} className="h-[420px] w-full" />;
}
