import { useEffect, useMemo, useRef } from "react";
import uPlot, { type AlignedData, type Options } from "uplot";
import "uplot/dist/uPlot.min.css";

import type { SeriesPoint } from "../api/types";
import { formatTemperature } from "../format";
import styles from "./TemperatureChart.module.css";

interface Props {
  points: SeriesPoint[];
  low: number;
  high: number;
  timeZone: string;
  expectedIntervalSeconds: number;
}

/**
 * Builds uPlot data. A pause longer than 2.5 expected intervals and a failed probe reading become `null`,
 * so the line is broken there instead of drawing a value that was never measured.
 */
export function chartData(points: SeriesPoint[], low: number, high: number, intervalSeconds: number): AlignedData {
  const times: number[] = [];
  const values: (number | null)[] = [];
  let previous: number | null = null;
  for (const point of points) {
    const time = Math.round(new Date(point.t).getTime() / 1000);
    if (previous !== null && time - previous > intervalSeconds * 2.5) {
      times.push(previous + 1);
      values.push(null);
    }
    times.push(time);
    values.push(point.ok ? point.value : null);
    previous = time;
  }
  return [times, values, times.map(() => high), times.map(() => low)];
}

export function TemperatureChart({ points, low, high, timeZone, expectedIntervalSeconds }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const data = useMemo(
    () => chartData(points, low, high, expectedIntervalSeconds),
    [points, low, high, expectedIntervalSeconds],
  );

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const options: Options = {
      width: element.clientWidth,
      height: 280,
      tzDate: (seconds) => uPlot.tzDate(new Date(seconds * 1000), timeZone),
      cursor: { drag: { x: true, y: false } },
      legend: { show: true },
      scales: { x: { time: true } },
      axes: [
        {
          stroke: "#55636d",
          grid: { stroke: "#e6ebee" },
          size: 48,
          values: (_chart, ticks, _axis, _space, increment) => {
            // Russian 24-hour labels in the site's zone; dates appear when ticks are a day or more apart.
            const format = new Intl.DateTimeFormat("ru-RU", {
              timeZone,
              ...(increment >= 86_400 ? { day: "2-digit", month: "2-digit" } : { hour: "2-digit", minute: "2-digit" }),
            });
            return ticks.map((tick) => format.format(new Date(tick * 1000)));
          },
        },
        {
          stroke: "#55636d",
          grid: { stroke: "#e6ebee" },
          size: 64,
          values: (_chart, ticks) => ticks.map((tick) => `${tick.toLocaleString("ru-RU")} °C`),
        },
      ],
      series: [
        { label: "Время" },
        {
          label: "Температура",
          stroke: "#165d7a",
          width: 2,
          spanGaps: false,
          value: (_chart, value) => formatTemperature(value),
        },
        { label: "Верхний порог", stroke: "#b42318", width: 1, dash: [6, 4], value: (_c, v) => formatTemperature(v) },
        { label: "Нижний порог", stroke: "#1d5fb4", width: 1, dash: [6, 4], value: (_c, v) => formatTemperature(v) },
      ],
    };
    const chart = new uPlot(options, data, element);
    const observer = new ResizeObserver(() => {
      chart.setSize({ width: element.clientWidth, height: 280 });
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      chart.destroy();
    };
  }, [data, timeZone]);

  return (
    <figure className={styles.figure}>
      <div ref={container} className={styles.chart} />
      <figcaption className="visually-hidden">
        График температуры: {points.length} измерений, пороги {formatTemperature(low)} и {formatTemperature(high)}
      </figcaption>
    </figure>
  );
}
