"use client";

// Interactive intelligence map card under an assistant reply (show_map).
// The message keeps only MapCardInfo; the full payload is fetched by map_id.
import React, { useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { visualsApi } from "@/lib/api/documents";
import { useChatStore } from "@/lib/stores/chatStore";
import type { MapCardInfo, MapFeature } from "@/types";
import { LAYER_ICON, SEVERITY_COLOR, SEVERITY_LABEL, VERDICT_LABEL, formatTime, iconSvg } from "./intelStyle";

const MapView = dynamic(() => import("./MapView"), {
  ssr: false,
  loading: () => <div className="absolute inset-0 animate-pulse bg-secondary/40" />,
});

interface MapCardProps {
  info: MapCardInfo;
  onAsk?: (text: string) => void; // sends a chat message (used for "Send to TAK")
}

function DetailPanel({ f, onClose, onAsk }: { f: MapFeature; onClose: () => void; onAsk?: (t: string) => void }) {
  const takEnabled = useChatStore((s) => s.takEnabled);
  const color = SEVERITY_COLOR[f.severity] || "#B2AA7D";
  const details = Object.entries(f.details || {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  return (
    <div className="absolute left-2 right-2 bottom-2 sm:left-auto sm:right-2 sm:top-2 sm:bottom-2 sm:w-80 z-10 rounded-lg border border-border bg-white/95 dark:bg-[#101514]/95 backdrop-blur shadow-xl flex flex-col max-h-[70%] sm:max-h-none">
      <div className="flex items-start gap-2 p-3 border-b border-border">
        <span
          className="mt-0.5 shrink-0"
          dangerouslySetInnerHTML={{ __html: iconSvg(LAYER_ICON[f.layer] || "hotspot", color, 18) }}
        />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold text-foreground leading-snug">{f.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className="text-[10.5px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded" style={{ color, border: `1px solid ${color}` }}>
              {SEVERITY_LABEL[f.severity] || f.severity}
            </span>
            {f.time && <span className="text-[11px] text-muted-foreground">{formatTime(f.time)}</span>}
          </div>
        </div>
        <button onClick={onClose} aria-label="Close details" className="shrink-0 w-7 h-7 rounded-md text-muted-foreground hover:bg-secondary flex items-center justify-center">
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </div>
      <div className="p-3 overflow-y-auto text-[12.5px] space-y-2">
        {f.verdict && (
          <div className={`rounded-md px-2 py-1.5 text-[12px] ${f.verdict === "corroborated" || f.verdict === "official_source" ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400" : "bg-amber-500/10 text-amber-800 dark:text-amber-300"}`}>
            {VERDICT_LABEL[f.verdict] || f.verdict.replace(/_/g, " ")}
          </div>
        )}
        {f.text && (
          <blockquote className="border-l-2 border-border pl-2 text-muted-foreground whitespace-pre-line">{f.text}</blockquote>
        )}
        {details.length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            {details.map(([k, v]) => (
              <React.Fragment key={k}>
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="text-foreground font-mono text-[12px] break-words">{String(v)}</dd>
              </React.Fragment>
            ))}
          </dl>
        )}
        <div className="text-[11px] text-muted-foreground">
          Source: {f.source} · {f.lat.toFixed(3)}, {f.lon.toFixed(3)}
        </div>
      </div>
      <div className="p-2 border-t border-border flex flex-wrap gap-2">
        {f.url && (
          <a href={f.url} target="_blank" rel="noopener noreferrer" className="text-[12px] px-2.5 py-1 rounded-md border border-border hover:bg-secondary text-foreground">
            Open source ↗
          </a>
        )}
        {takEnabled && onAsk && (
          <button
            onClick={() => onAsk(`Place a TAK marker for "${f.title}" at ${f.lat.toFixed(5)}, ${f.lon.toFixed(5)} with this note: ${f.source}${f.verdict ? `, ${f.verdict.replace(/_/g, " ")}` : ""}.`)}
            className="text-[12px] px-2.5 py-1 rounded-md bg-brand text-brand-foreground hover:bg-brand-hover"
          >
            Send to TAK
          </button>
        )}
      </div>
    </div>
  );
}

function MapBody({ info, expanded, onAsk }: { info: MapCardInfo; expanded: boolean; onAsk?: (t: string) => void }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<MapFeature | null>(null);
  const q = useQuery({
    queryKey: ["intel-map", info.map_id],
    queryFn: () => visualsApi.getMap(info.map_id),
    staleTime: Infinity,
    retry: 1,
  });
  const toggle = (id: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <>
      <div className={`relative w-full overflow-hidden ${expanded ? "flex-1" : "h-[340px] sm:h-[380px]"} bg-[#0B0F0E]`}>
        {q.isLoading && <div className="absolute inset-0 animate-pulse bg-secondary/40" />}
        {q.isError && (
          <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-[13px] text-muted-foreground">
            This map is no longer available (maps are kept for 30 days). Ask the assistant to draw it again.
          </div>
        )}
        {q.data && (
          <MapView
            key={`${info.map_id}-${expanded ? "x" : "c"}`}
            payload={q.data}
            hiddenLayers={hidden}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
            expanded={expanded}
          />
        )}
        {selected && <DetailPanel f={selected} onClose={() => setSelected(null)} onAsk={onAsk} />}
      </div>
      <div className="px-3 py-2 flex flex-wrap gap-1.5 border-t border-border">
        {info.layers.map((l) => {
          const off = hidden.has(l.id);
          return (
            <button
              key={l.id}
              onClick={() => toggle(l.id)}
              aria-pressed={!off}
              disabled={l.count === 0}
              className={`inline-flex items-center gap-1.5 text-[11.5px] px-2 py-1 rounded-full border transition-colors disabled:opacity-40 ${
                off ? "border-border text-muted-foreground line-through" : "border-border bg-secondary/60 text-foreground"
              }`}
            >
              <span dangerouslySetInnerHTML={{ __html: iconSvg(LAYER_ICON[l.id] || "hotspot", off ? "#5C6259" : "#B2AA7D", 13) }} />
              {l.label}
              <span className="font-mono text-muted-foreground">{l.count}</span>
            </button>
          );
        })}
      </div>
      {q.data && (q.data.notes.length > 0 || q.data.sources.some((s) => !s.ok)) && (
        <details className="px-3 pb-2 text-[11.5px] text-muted-foreground">
          <summary className="cursor-pointer select-none">Caveats and sources</summary>
          <ul className="mt-1 list-disc pl-4 space-y-0.5">
            {q.data.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
            {q.data.sources.map((s) => (
              <li key={s.name}>
                {s.name}: {s.ok ? "ok" : "unavailable"}
                {s.fetched_at ? ` (fetched ${formatTime(s.fetched_at)})` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

export default function MapCard({ info, onAsk }: MapCardProps) {
  const [expanded, setExpanded] = useState(false);
  const header = (
    <div className="px-3 py-2 flex items-center gap-2 border-b border-border">
      <svg className="w-4 h-4 text-[#B2AA7D] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14" />
      </svg>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold text-foreground truncate">{info.title}</div>
        <div className="text-[11px] text-muted-foreground">
          {info.icon_count} items · last {info.hours} h · tap an icon for details
        </div>
      </div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="shrink-0 text-[12px] px-2.5 py-1 rounded-md border border-border hover:bg-secondary text-foreground"
        aria-label={expanded ? "Close full screen" : "Open full screen"}
      >
        {expanded ? "Close" : "Expand"}
      </button>
    </div>
  );

  return (
    <>
      <div className="mt-3 rounded-lg border border-border bg-white dark:bg-[#101514] overflow-hidden">
        {header}
        {!expanded && <MapBody info={info} expanded={false} onAsk={onAsk} />}
        {expanded && <div className="h-24 flex items-center justify-center text-[12px] text-muted-foreground">Open in full screen</div>}
      </div>
      {expanded && (
        <div className="fixed inset-0 z-50 bg-white dark:bg-[#0B0F0E] flex flex-col" role="dialog" aria-modal="true" aria-label={info.title}>
          {header}
          <MapBody info={info} expanded onAsk={onAsk} />
        </div>
      )}
    </>
  );
}
