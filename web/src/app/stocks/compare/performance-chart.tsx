"use client";

import { ColorType, LineSeries, LineStyle, type Time, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { Performance } from "@/lib/api";

export type Line = { p: Performance; color: string; dashed?: boolean };

// Each stock's adjusted close, and Nifty 500's, rebased to 100 on the same first day:
// 130 means up 30% since then.
export function PerformanceChart({ lines }: { lines: Line[] }) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const chart = createChart(el, {
      autoSize: true,
      localization: { locale: "en-IN", priceFormatter: (v: number) => v.toFixed(0) },
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
      handleScroll: false,
      handleScale: false,
    });
    lines.forEach(({ p, color, dashed }, i) => {
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: dashed ? 1 : 2,
        lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: true,
        title: p.symbol,
      });
      series.setData(p.series.map((x) => ({ time: x.time as Time, value: x.value })));
      if (i === 0) {
        series.createPriceLine({ price: 100, color: dark ? "#525252" : "#a3a3a3", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
      }
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [lines]);

  return <div ref={box} className="h-64 w-full sm:h-80" role="img" aria-label="Price performance, rebased to 100" />;
}
