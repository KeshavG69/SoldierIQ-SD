"use client";

// Chart / timeline card under an assistant reply (create_chart).
import React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "@/types";
import { SEVERITY_COLOR, formatTime } from "./intelStyle";

const PALETTE = ["#B2AA7D", "#CC4B39", "#7FA65E", "#D6A43C", "#8FA3B8", "#837B54"];

function fmt(v: number | null | undefined, f?: string): string {
  if (v == null) return "–";
  if (f === "percent") return `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
  if (f === "currency") return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function Timeline({ spec }: { spec: ChartSpec }) {
  const events = [...(spec.events || [])].sort((a, b) => (a.time > b.time ? 1 : -1));
  return (
    <ol className="relative ml-2 border-l border-border pl-4 py-1 space-y-3">
      {events.map((e, i) => (
        <li key={`${e.time}-${i}`} className="relative">
          <span
            className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full ring-2 ring-white dark:ring-[#101514]"
            style={{ background: e.severity ? SEVERITY_COLOR[e.severity] : "#B2AA7D" }}
          />
          <div className="text-[11px] font-mono text-muted-foreground">{formatTime(e.time) || e.time}</div>
          <div className="text-[13px] text-foreground font-medium">{e.label}</div>
          {e.detail && <div className="text-[12px] text-muted-foreground">{e.detail}</div>}
        </li>
      ))}
    </ol>
  );
}

export default function ChartCard({ spec }: { spec: ChartSpec }) {
  const categories = spec.categories || [];
  const series = spec.series || [];
  const rows = categories.map((c, i) => {
    const row: Record<string, string | number | null> = { name: c };
    series.forEach((s) => (row[s.name] = s.data[i] ?? null));
    return row;
  });
  const axisProps = { tick: { fontSize: 11, fill: "#99A08F" }, stroke: "#2C3430" };
  const tooltip = (
    <Tooltip
      formatter={(v: unknown) => fmt(typeof v === "number" ? v : null, spec.value_format)}
      contentStyle={{ background: "#101514", border: "1px solid #2C3430", fontSize: 12, color: "#E7E6DC" }}
    />
  );
  const legend = series.length > 1 ? <Legend wrapperStyle={{ fontSize: 11 }} /> : null;

  let chart: React.ReactNode = null;
  if (spec.kind === "line") {
    chart = (
      <LineChart data={rows}>
        <CartesianGrid stroke="#1F2624" />
        <XAxis dataKey="name" {...axisProps} />
        <YAxis {...axisProps} tickFormatter={(v) => fmt(v, spec.value_format)} />
        {tooltip}
        {legend}
        {series.map((s, i) => (
          <Line key={s.name} type="monotone" dataKey={s.name} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2} dot={false} connectNulls />
        ))}
      </LineChart>
    );
  } else if (spec.kind === "area") {
    chart = (
      <AreaChart data={rows}>
        <CartesianGrid stroke="#1F2624" />
        <XAxis dataKey="name" {...axisProps} />
        <YAxis {...axisProps} tickFormatter={(v) => fmt(v, spec.value_format)} />
        {tooltip}
        {legend}
        {series.map((s, i) => (
          <Area key={s.name} type="monotone" dataKey={s.name} stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.2} connectNulls />
        ))}
      </AreaChart>
    );
  } else if (spec.kind === "donut") {
    const s = series[0];
    const data = categories.map((c, i) => ({ name: c, value: s?.data[i] ?? 0 }));
    chart = (
      <PieChart>
        {tooltip}
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Pie data={data} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="80%" paddingAngle={1}>
          {data.map((_, i) => (
            <Cell key={i} fill={PALETTE[i % PALETTE.length]} stroke="none" />
          ))}
        </Pie>
      </PieChart>
    );
  } else if (spec.kind !== "timeline") {
    const horizontal = spec.kind === "bar";
    chart = (
      <BarChart data={rows} layout={horizontal ? "vertical" : "horizontal"}>
        <CartesianGrid stroke="#1F2624" />
        {horizontal ? (
          <>
            <XAxis type="number" {...axisProps} tickFormatter={(v) => fmt(v, spec.value_format)} />
            <YAxis type="category" dataKey="name" width={110} {...axisProps} />
          </>
        ) : (
          <>
            <XAxis dataKey="name" {...axisProps} />
            <YAxis {...axisProps} tickFormatter={(v) => fmt(v, spec.value_format)} />
          </>
        )}
        {tooltip}
        {legend}
        {series.map((s, i) => (
          <Bar key={s.name} dataKey={s.name} fill={PALETTE[i % PALETTE.length]} radius={2} />
        ))}
      </BarChart>
    );
  }

  return (
    <figure className="mt-3 rounded-lg border border-border bg-white dark:bg-[#101514] p-3">
      {spec.title && <figcaption className="text-[13px] font-semibold text-foreground">{spec.title}</figcaption>}
      {spec.subtitle && <div className="text-[12px] text-muted-foreground">{spec.subtitle}</div>}
      <div className="mt-2">
        {spec.kind === "timeline" ? (
          <Timeline spec={spec} />
        ) : (
          <div className="h-[260px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              {chart as React.ReactElement}
            </ResponsiveContainer>
          </div>
        )}
      </div>
      {(spec.y_title || spec.x_title || spec.source) && (
        <div className="mt-2 text-[11px] text-muted-foreground flex flex-wrap gap-x-3">
          {spec.y_title && <span>Y: {spec.y_title}</span>}
          {spec.x_title && <span>X: {spec.x_title}</span>}
          {spec.source && <span>Source: {spec.source}</span>}
        </div>
      )}
    </figure>
  );
}
