// Icons and colours for intelligence map layers. Colours follow DESIGN.md:
// signal red for critical, warn amber for high/elevated, olive for routine.
import type { IntelSeverity } from "@/types";

export const SEVERITY_COLOR: Record<IntelSeverity, string> = {
  critical: "#CC4B39",
  high: "#E07A3F",
  elevated: "#D6A43C",
  moderate: "#B2AA7D",
  low: "#7FA65E",
  info: "#8FA3B8",
};

export const SEVERITY_LABEL: Record<IntelSeverity, string> = {
  critical: "Critical",
  high: "High",
  elevated: "Elevated",
  moderate: "Moderate",
  low: "Low",
  info: "Info",
};

export const VERDICT_LABEL: Record<string, string> = {
  official_source: "Official source",
  corroborated: "Corroborated by an independent source",
  single_source: "Single source, unconfirmed",
  uncorroborated_partisan: "Partisan source, unconfirmed",
  news_coded_unverified: "Machine-coded from news, unverified",
};

// 24x24 SVG path data (stroke icons) per layer.
const PATHS: Record<string, string> = {
  strike: "M12 2l2.4 6.6L21 9l-5 4.4L17.5 21 12 17.3 6.5 21 8 13.4 3 9l6.6-.4z",
  aircraft: "M12 2c.8 0 1.4.9 1.4 2v5.2l7.6 4.3v2l-7.6-2.3v4.6l2.4 1.8V21L12 20l-3.8 1v-1.4l2.4-1.8v-4.6L3 15.5v-2l7.6-4.3V4c0-1.1.6-2 1.4-2z",
  conflict: "M5 3l14 14M19 3L5 17M3 21h18",
  chokepoint: "M4 16c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2M4 20c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2M12 3v8M8 7h8",
  hotspot: "M12 3v4M12 17v4M3 12h4M17 12h4M12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0-6 0",
  quake: "M2 12h4l2-6 4 12 3-9 2 3h5",
  hazard: "M12 3l10 18H2zM12 10v5M12 18v.5",
  outage: "M2 8.5a15 15 0 0 1 20 0M5 12a10 10 0 0 1 14 0M8.5 15.5a5 5 0 0 1 7 0M12 19h.01M3 3l18 18",
  fire: "M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-3 2-4 2-7 1.5 1 3 3 3 5 0-3 0-5 0-8z",
  ship: "M3 17l2 4h14l2-4-9-3zM12 3v11M8 7h8l-1 4H9z",
};

export function iconSvg(icon: string, color: string, size = 18, rotate?: number | null): string {
  const d = PATHS[icon] || PATHS.hotspot;
  const filled = icon === "aircraft" || icon === "strike";
  const rot = rotate != null && icon === "aircraft" ? ` style="transform:rotate(${rotate}deg)"` : "";
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24"${rot} fill="${filled ? color : "none"}" stroke="${
    filled ? "#0B0F0E" : color
  }" stroke-width="${filled ? 1 : 2.2}" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
}

export const LAYER_ICON: Record<string, string> = {
  strikes: "strike",
  aircraft: "aircraft",
  conflict: "conflict",
  chokepoints: "chokepoint",
  hotspots: "hotspot",
  quakes: "quake",
  disasters: "hazard",
  outages: "outage",
  fires: "fire",
  ships: "ship",
};

export function formatTime(t: string | null | undefined): string {
  if (!t) return "";
  // GDELT stamps look like 20261113121500
  const m = /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})/.exec(t);
  const d = m ? new Date(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:00Z`) : new Date(t);
  if (isNaN(d.getTime())) return t;
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  const abs = d.toISOString().replace("T", " ").slice(0, 16) + "Z";
  if (mins >= 0 && mins < 60) return `${mins} min ago · ${abs}`;
  if (mins >= 60 && mins < 48 * 60) return `${Math.round(mins / 60)} h ago · ${abs}`;
  return abs;
}
