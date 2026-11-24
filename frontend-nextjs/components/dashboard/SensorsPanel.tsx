"use client";

/**
 * Sensors — the "Sensors" tab of the Connectors modal.
 *
 * Admins add sensors to the organization:
 *   - Phone: camera + GPS + compass. SoldierIQ shows a QR code; the phone opens
 *     the sensor hub's page with a pairing token and starts streaming.
 *   - GPS tracker: any tracker Traccar understands (or the Traccar Client app).
 *     Identified by its device ID / IMEI; SoldierIQ registers it in Traccar.
 * Everyone in the org sees the list, live status, latest readings and video.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import {
  ArrowLeft, Cctv, Check, ChevronDown, Copy, MapPin, Pause, Pencil, Play, Plus, QrCode, RefreshCw, Settings2, Smartphone,
  Trash2,
} from "lucide-react";
import { CameraBrand, CameraConfigInput, CameraConfigView, FeedType, sensorsApi, Sensor, SensorType } from "@/lib/api/sensors";
import { AlertWatchEditor, DetectionReadout, RecentAlerts } from "./SensorAlerts";

const inputCls =
  "w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15 transition-all";
const labelCls = "block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5";
const hintCls = "text-[11px] text-muted-foreground mt-1";
const btnCls =
  "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50 transition-colors";
const primaryCls =
  "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand text-brand-foreground text-xs font-medium hover:bg-brand-hover disabled:opacity-50 transition-colors";

const TYPE_LABEL: Record<SensorType, string> = { phone: "Phone", gps_tracker: "GPS tracker", ip_camera: "IP camera" };
const TYPE_ICON: Record<SensorType, typeof Smartphone> = { phone: Smartphone, gps_tracker: MapPin, ip_camera: Cctv };

type View = { kind: "list" } | { kind: "add" } | { kind: "setup"; id: string };

function errText(err: any, fallback: string): string {
  return err?.response?.data?.detail || err?.message || fallback;
}

function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 5) return "just now";
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

function StatusPill({ status }: { status: Sensor["status"] }) {
  const map: Record<Sensor["status"], [string, string]> = {
    live: ["Live", "bg-emerald-500/15 text-emerald-500"],
    offline: ["Offline", "bg-red-500/10 text-red-500"],
    waiting: ["Waiting for data", "bg-amber-500/15 text-amber-500"],
    paused: ["Paused", "bg-secondary text-muted-foreground"],
  };
  const [label, cls] = map[status];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap ${cls}`}>
      {status === "live" && <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />}
      {label}
    </span>
  );
}

/** A hub on this computer / LAN (self-signed HTTPS, phone must share the network) vs a hosted one. */
function isLanHub(url: string): boolean {
  try {
    const host = new URL(url).hostname;
    return (
      host === "localhost" ||
      host.endsWith(".local") ||
      /^(10|127)\.|^192\.168\.|^172\.(1[6-9]|2\d|3[01])\./.test(host)
    );
  } catch {
    return false;
  }
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <div className={labelCls}>{label}</div>
      <div className="flex items-center gap-2">
        <code className="flex-1 min-w-0 truncate px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm font-mono text-foreground">
          {value}
        </code>
        <button
          type="button"
          className={btnCls}
          onClick={() => {
            navigator.clipboard?.writeText(value).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1200);
            });
          }}
          aria-label={`Copy ${label}`}
        >
          {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  );
}

/**
 * Live camera. Loops "fetch newest frame -> show it -> fetch the next one" against the hub
 * (signed URL). Unlike an MJPEG stream this can never build up a backlog: if the network or
 * browser is slow, frames are skipped and what you see is always the latest one.
 */
function LiveVideo({ sensor }: { sensor: Sensor }) {
  const [src, setSrc] = useState<string | null>(null);
  const [delayMs, setDelayMs] = useState<number | null>(null);
  const live = sensor.status === "live";

  useEffect(() => {
    if (!live) {
      setSrc(null);
      return;
    }
    let stopped = false;
    let objectUrl: string | null = null;
    (async () => {
      let frameUrl: string | null = null;
      let expires = 0;
      let seq = -1;
      while (!stopped) {
        try {
          if (!frameUrl || Date.now() / 1000 > expires - 60) {
            const r = await sensorsApi.streamUrl(sensor.id);
            frameUrl = r.frame_url;
            expires = r.expires;
          }
          const res = await fetch(`${frameUrl}&after=${seq}`, { cache: "no-store" });
          if (res.status === 403) {
            frameUrl = null;
            continue;
          }
          if (!res.ok) throw new Error(String(res.status));
          seq = Number(res.headers.get("X-Frame-Seq") ?? seq);
          const captured = Number(res.headers.get("X-Captured-Ts") || 0);
          const blob = await res.blob();
          if (stopped) break;
          const next = URL.createObjectURL(blob);
          setSrc(next);
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          objectUrl = next;
          if (captured) setDelayMs(Math.max(0, Date.now() - captured));
        } catch {
          await new Promise((r) => setTimeout(r, 1000));
        }
      }
    })();
    return () => {
      stopped = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [sensor.id, live]);

  return (
    <div className="relative w-full aspect-video rounded-lg bg-black overflow-hidden grid place-items-center">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={`Live camera: ${sensor.name}`} className="absolute inset-0 w-full h-full object-contain" />
      ) : (
        <span className="text-xs text-white/60">{live ? "Connecting to camera…" : "Camera offline"}</span>
      )}
      {src && delayMs !== null && (
        <span className="absolute top-2 left-2 px-1.5 py-0.5 rounded bg-black/60 text-[10px] text-white/80 tabular-nums">
          {delayMs < 1000 ? `${delayMs} ms` : `${(delayMs / 1000).toFixed(1)} s`} delay
        </span>
      )}
    </div>
  );
}

function Readings({ sensor }: { sensor: Sensor }) {
  const p = sensor.latest.position?.data;
  const o = sensor.latest.orientation?.data;
  const b = sensor.latest.status?.data;
  const rows: [string, React.ReactNode][] = [
    [
      "Position",
      p ? (
        <a
          className="text-brand hover:underline"
          href={`https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=17/${p.lat}/${p.lon}`}
          target="_blank"
          rel="noreferrer"
        >
          {p.lat.toFixed(5)}, {p.lon.toFixed(5)}
        </a>
      ) : (
        "–"
      ),
    ],
    ["Accuracy", p?.accuracy_m != null ? `±${Math.round(p.accuracy_m)} m` : "–"],
    ["Speed", p?.speed_mps != null ? `${(p.speed_mps * 3.6).toFixed(1)} km/h` : "–"],
    ["Altitude", p?.alt_m != null ? `${Math.round(p.alt_m)} m` : "–"],
  ];
  if (sensor.sensor_type === "ip_camera") {
    const fps = (sensor.latest.status?.data as { fps?: number } | undefined)?.fps;
    return (
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
        {([
          rows[0],
          ["Video", sensor.status === "live" && fps ? `${fps} frames/s` : "–"],
          ["Last seen", ago(sensor.last_seen)],
        ] as [string, React.ReactNode][]).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-foreground tabular-nums min-w-0 truncate">{v}</dd>
          </div>
        ))}
      </dl>
    );
  }
  if (sensor.sensor_type === "phone") {
    rows.push(["Heading", o?.heading_deg != null ? `${Math.round(o.heading_deg)}°` : "–"]);
  } else {
    rows.push(["Course", p?.course_deg != null ? `${Math.round(p.course_deg)}°` : "–"]);
  }
  rows.push(["Battery", b?.battery_pct != null ? `${b.battery_pct}%${b.charging ? " (charging)" : ""}` : "–"]);
  rows.push(["Last seen", ago(sensor.last_seen)]);
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="text-foreground tabular-nums min-w-0 truncate">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function SensorRow({
  sensor, isAdmin, onSetup, onChanged,
}: {
  sensor: Sensor;
  isAdmin: boolean;
  onSetup: () => void;
  onChanged: (msg?: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const Icon = TYPE_ICON[sensor.sensor_type];

  const act = async (fn: () => Promise<unknown>, fail: string) => {
    setBusy(true);
    try {
      await fn();
      onChanged();
    } catch (e) {
      onChanged(errText(e, fail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-border overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-accent/50 transition-colors"
        aria-expanded={open}
      >
        <span className="w-8 h-8 shrink-0 rounded-lg bg-secondary grid place-items-center">
          <Icon className="w-4 h-4 text-muted-foreground" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-foreground truncate">{sensor.name}</span>
          <span className="block text-xs text-muted-foreground truncate">
            {TYPE_LABEL[sensor.sensor_type]}
            {sensor.identifier ? ` · ${sensor.identifier}` : ""} · {ago(sensor.last_seen)}
          </span>
        </span>
        <StatusPill status={sensor.status} />
        <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 space-y-3 border-t border-border">
          <div className={`grid gap-4 pt-3 ${sensor.has_camera ? "sm:grid-cols-[1.4fr_1fr]" : ""}`}>
            {sensor.has_camera && <LiveVideo sensor={sensor} />}
            <Readings sensor={sensor} />
          </div>
          {sensor.has_camera && <DetectionReadout sensor={sensor} />}
          {sensor.has_camera && <AlertWatchEditor sensor={sensor} isAdmin={isAdmin} onSaved={() => onChanged()} />}
          {isAdmin && (
            <div className="flex flex-wrap gap-2">
              <button type="button" className={btnCls} onClick={onSetup} disabled={busy}>
                {sensor.sensor_type === "ip_camera" ? <Settings2 className="w-3.5 h-3.5" /> : <QrCode className="w-3.5 h-3.5" />}{" "}
                {sensor.sensor_type === "phone" ? "Pairing QR" : sensor.sensor_type === "ip_camera" ? "Connection" : "Setup details"}
              </button>
              <button
                type="button"
                className={btnCls}
                disabled={busy}
                onClick={() => {
                  const name = prompt("Sensor name", sensor.name)?.trim();
                  if (name && name !== sensor.name) act(() => sensorsApi.update(sensor.id, { name }), "Rename failed");
                }}
              >
                <Pencil className="w-3.5 h-3.5" /> Rename
              </button>
              <button
                type="button"
                className={btnCls}
                disabled={busy}
                onClick={() => act(() => sensorsApi.update(sensor.id, { enabled: !sensor.enabled }), "Update failed")}
              >
                {sensor.enabled ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                {sensor.enabled ? "Pause" : "Resume"}
              </button>
              <button
                type="button"
                className={`${btnCls} ml-auto hover:!text-red-500 hover:!border-red-500/40`}
                disabled={busy}
                onClick={() => {
                  if (confirm(`Remove "${sensor.name}"? It will stop sending data and its history will be deleted.`)) {
                    act(() => sensorsApi.remove(sensor.id), "Remove failed");
                  }
                }}
              >
                <Trash2 className="w-3.5 h-3.5" /> Remove
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AddSensor({ onCancel, onCreated }: { onCancel: () => void; onCreated: (s: Sensor) => void }) {
  const [type, setType] = useState<SensorType>("phone");
  const [name, setName] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [camera, setCamera] = useState<CameraForm>(emptyCamera());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    if (!name.trim()) return setError("Give the sensor a name, e.g. “North gate camera”.");
    let cam: CameraConfigInput | undefined;
    if (type === "ip_camera") {
      const r = cameraInput(camera, true);
      if (typeof r === "string") return setError(r);
      cam = r;
    }
    setSaving(true);
    try {
      const s = await sensorsApi.create({
        name: name.trim(),
        sensor_type: type,
        identifier: type === "gps_tracker" && identifier.trim() ? identifier.trim() : undefined,
        camera: cam,
      });
      onCreated(s);
    } catch (e) {
      setError(errText(e, "Could not add the sensor"));
    } finally {
      setSaving(false);
    }
  };

  const types: { id: SensorType; title: string; body: string; Icon: typeof Smartphone }[] = [
    { id: "phone", title: "Phone", body: "Camera, GPS and compass. Pair by scanning a QR code.", Icon: Smartphone },
    { id: "ip_camera", title: "Camera (CCTV)", body: "An IP camera (Hikvision, Dahua, CP Plus), an HLS video stream, or a refreshing image URL.", Icon: Cctv },
    { id: "gps_tracker", title: "GPS tracker", body: "A GPS tracker, or a phone running the Traccar Client app.", Icon: MapPin },
  ];

  return (
    <div className="space-y-5">
      <button type="button" className={btnCls} onClick={onCancel}>
        <ArrowLeft className="w-3.5 h-3.5" /> Back
      </button>
      <div>
        <div className={labelCls}>Sensor type</div>
        <div className="grid sm:grid-cols-3 gap-2" role="radiogroup" aria-label="Sensor type">
          {types.map(({ id, title, body, Icon }) => (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={type === id}
              onClick={() => setType(id)}
              className={`text-left rounded-xl border px-4 py-3 transition-colors ${
                type === id ? "border-brand bg-brand/5" : "border-border hover:bg-accent/50"
              }`}
            >
              <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Icon className="w-4 h-4" /> {title}
              </div>
              <p className="text-xs text-muted-foreground mt-1">{body}</p>
            </button>
          ))}
        </div>
      </div>
      <div>
        <label htmlFor="sensor-name" className={labelCls}>Name *</label>
        <input
          id="sensor-name"
          className={inputCls}
          value={name}
          maxLength={60}
          onChange={(e) => setName(e.target.value)}
          placeholder={type === "gps_tracker" ? "e.g. Patrol vehicle 2" : "e.g. North gate camera"}
          autoFocus
        />
      </div>
      {type === "ip_camera" && <CameraFields value={camera} onChange={setCamera} />}
      {type === "gps_tracker" && (
        <div>
          <label htmlFor="sensor-ident" className={labelCls}>Device ID / IMEI</label>
          <input
            id="sensor-ident"
            className={`${inputCls} font-mono`}
            value={identifier}
            maxLength={40}
            onChange={(e) => setIdentifier(e.target.value)}
            placeholder="e.g. 356307042441013"
          />
          <p className={hintCls}>
            For a hardware tracker, enter the IMEI printed on it. Leave empty to generate an ID for the Traccar Client app.
          </p>
        </div>
      )}
      {error && <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-500">{error}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" className={btnCls} onClick={onCancel} disabled={saving}>Cancel</button>
        <button type="button" className={primaryCls} onClick={submit} disabled={saving}>
          {saving ? "Adding…" : "Add sensor"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Camera (CCTV): RTSP, HLS or snapshot

type CameraForm = {
  feed_type: FeedType;
  brand: CameraBrand;
  host: string;
  port: string;
  channel: string;
  stream: "main" | "sub";
  path: string;
  url: string;
  interval: string;
  username: string;
  password: string;
  lat: string;
  lon: string;
};

const FEED_TYPES: { id: FeedType; label: string; hint: string }[] = [
  { id: "rtsp", label: "IP camera (RTSP)", hint: "A camera on a network — Hikvision, Dahua, CP Plus, or any RTSP camera or recorder. Smooth live video." },
  { id: "hls", label: "Video stream (HLS)", hint: "A public or hosted video stream whose address ends in .m3u8 (many city / traffic cameras). Smooth live video." },
  { id: "snapshot", label: "Image URL (snapshot)", hint: "A still-image address that updates itself (e.g. a traffic cam that posts a JPEG). Refreshing photo, not smooth video." },
];

const BRANDS: { id: CameraBrand; label: string; hint: string }[] = [
  { id: "hikvision", label: "Hikvision", hint: "Also HiLook, Annke and most Hikvision-based cameras and recorders." },
  { id: "dahua", label: "Dahua / CP Plus", hint: "Also Amcrest, Lorex and other Dahua-based cameras and recorders." },
  { id: "custom", label: "Other (RTSP path)", hint: "Enter the stream path from the camera's manual, e.g. /live/ch0." },
];

function emptyCamera(c?: CameraConfigView): CameraForm {
  return {
    feed_type: c?.feed_type ?? "rtsp",
    brand: c?.brand ?? "hikvision",
    host: c?.host ?? "",
    port: String(c?.port ?? 554),
    channel: String(c?.channel ?? 1),
    stream: c?.stream ?? "sub",
    path: c?.brand === "custom" ? (c.path ?? "") : "",
    url: c?.url ?? "",
    interval: c?.interval_s != null ? String(c.interval_s) : "2",
    username: c?.username ?? (c ? "" : "admin"),
    password: "",
    lat: c?.lat != null ? String(c.lat) : "",
    lon: c?.lon != null ? String(c.lon) : "",
  };
}

/** Form -> API body, or an error message. */
function cameraInput(f: CameraForm, isNew: boolean): CameraConfigInput | string {
  const lat = f.lat.trim() ? Number(f.lat) : null;
  const lon = f.lon.trim() ? Number(f.lon) : null;
  if ((lat === null) !== (lon === null) || (lat !== null && (isNaN(lat) || lat < -90 || lat > 90)) || (lon !== null && (isNaN(lon) || lon < -180 || lon > 180)))
    return "Give a valid latitude and longitude (both), or leave both empty.";
  const common = {
    feed_type: f.feed_type,
    username: f.username.trim(),
    ...(isNew || f.password ? { password: f.password } : {}),
    lat,
    lon,
  };
  if (f.feed_type === "rtsp") {
    const host = f.host.trim();
    if (!host) return "Enter the camera's IP address, e.g. 192.168.1.64.";
    if (/[/@\s]|:\/\//.test(host)) return "Enter only the camera's IP address or host name (no rtsp://, no path).";
    const port = Number(f.port || 554);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return "The RTSP port must be a number from 1 to 65535 (usually 554).";
    const channel = Number(f.channel || 1);
    if (!Number.isInteger(channel) || channel < 1 || channel > 64) return "The channel must be a number from 1 to 64.";
    if (f.brand === "custom" && !f.path.trim().startsWith("/")) return "Enter the stream path, starting with “/”.";
    return { ...common, brand: f.brand, host, port, channel, stream: f.stream, path: f.brand === "custom" ? f.path.trim() : undefined };
  }
  const url = f.url.trim();
  if (!/^https?:\/\//i.test(url)) return "Enter the full stream URL, starting with http:// or https://.";
  if (f.feed_type === "snapshot") {
    const interval = Number(f.interval || 2);
    if (isNaN(interval) || interval < 0.5 || interval > 60) return "The refresh interval must be between 0.5 and 60 seconds.";
    return { ...common, url, interval_s: interval };
  }
  return { ...common, url };
}

function CameraFields({ value: f, onChange, editing }: { value: CameraForm; onChange: (f: CameraForm) => void; editing?: boolean }) {
  const set = (k: keyof CameraForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    onChange({ ...f, [k]: e.target.value });
  const feed = FEED_TYPES.find((t) => t.id === f.feed_type)!;
  const brand = BRANDS.find((b) => b.id === f.brand)!;
  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="cam-feed" className={labelCls}>Feed type</label>
        <select id="cam-feed" className={inputCls} value={f.feed_type} onChange={set("feed_type")}>
          {FEED_TYPES.map((t) => (
            <option key={t.id} value={t.id}>{t.label}</option>
          ))}
        </select>
        <p className={hintCls}>{feed.hint}</p>
      </div>

      {f.feed_type === "rtsp" ? (
        <>
          <div>
            <label htmlFor="cam-brand" className={labelCls}>Camera make</label>
            <select id="cam-brand" className={inputCls} value={f.brand} onChange={set("brand")}>
              {BRANDS.map((b) => (
                <option key={b.id} value={b.id}>{b.label}</option>
              ))}
            </select>
            <p className={hintCls}>{brand.hint}</p>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_6rem] gap-3">
            <div>
              <label htmlFor="cam-host" className={labelCls}>IP address *</label>
              <input id="cam-host" className={`${inputCls} font-mono`} value={f.host} onChange={set("host")} placeholder="192.168.1.64" maxLength={253} />
            </div>
            <div>
              <label htmlFor="cam-port" className={labelCls}>RTSP port</label>
              <input id="cam-port" className={`${inputCls} font-mono`} value={f.port} onChange={set("port")} inputMode="numeric" maxLength={5} />
            </div>
          </div>
          {f.brand === "custom" ? (
            <div>
              <label htmlFor="cam-path" className={labelCls}>Stream path *</label>
              <input id="cam-path" className={`${inputCls} font-mono`} value={f.path} onChange={set("path")} placeholder="/live/ch0" maxLength={300} />
            </div>
          ) : (
            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <label htmlFor="cam-ch" className={labelCls}>Channel</label>
                <input id="cam-ch" className={`${inputCls} font-mono`} value={f.channel} onChange={set("channel")} inputMode="numeric" maxLength={2} />
                <p className={hintCls}>1 for a single camera. On a recorder (NVR/DVR), the camera&apos;s number.</p>
              </div>
              <div>
                <label htmlFor="cam-stream" className={labelCls}>Quality</label>
                <select id="cam-stream" className={inputCls} value={f.stream} onChange={set("stream")}>
                  <option value="sub">Sub stream (low resolution, recommended)</option>
                  <option value="main">Main stream (full resolution)</option>
                </select>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="space-y-4">
          <div>
            <label htmlFor="cam-url" className={labelCls}>{f.feed_type === "hls" ? "Stream URL (.m3u8) *" : "Image URL *"}</label>
            <input id="cam-url" className={`${inputCls} font-mono`} value={f.url} onChange={set("url")}
              placeholder={f.feed_type === "hls" ? "https://…/playlist.m3u8" : "https://…/camera.jpg"} maxLength={600} />
          </div>
          {f.feed_type === "snapshot" && (
            <div className="sm:w-40">
              <label htmlFor="cam-int" className={labelCls}>Refresh every</label>
              <div className="flex items-center gap-2">
                <input id="cam-int" className={`${inputCls} font-mono`} value={f.interval} onChange={set("interval")} inputMode="decimal" maxLength={4} />
                <span className="text-sm text-muted-foreground">sec</span>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label htmlFor="cam-user" className={labelCls}>Username{f.feed_type !== "rtsp" ? " (if needed)" : ""}</label>
          <input id="cam-user" className={inputCls} value={f.username} onChange={set("username")} autoComplete="off" maxLength={64} />
        </div>
        <div>
          <label htmlFor="cam-pass" className={labelCls}>Password</label>
          <input id="cam-pass" type="password" className={inputCls} value={f.password} onChange={set("password")}
            autoComplete="new-password" maxLength={128} placeholder={editing ? "Leave empty to keep the saved one" : ""} />
        </div>
      </div>

      <div>
        <div className={labelCls}>Location on the map (optional)</div>
        <div className="grid grid-cols-2 gap-3">
          <input aria-label="Latitude" className={`${inputCls} font-mono`} value={f.lat} onChange={set("lat")} placeholder="Latitude, e.g. 12.9716" />
          <input aria-label="Longitude" className={`${inputCls} font-mono`} value={f.lon} onChange={set("lon")} placeholder="Longitude, e.g. 77.5946" />
        </div>
      </div>
      <p className="rounded-lg border border-border bg-surface-2 px-3 py-2 text-xs text-muted-foreground">
        The sensor hub connects to the camera, so it must be able to reach this address. For a camera on a home or office
        network, run the sensor hub on a computer on that network. Any password is stored encrypted and is only given to the
        sensor hub.
      </p>
    </div>
  );
}

function CameraSetup({
  sensor, camera, streamError, onChanged,
}: {
  sensor: Sensor;
  camera: CameraConfigView;
  streamError?: string | null;
  onChanged: (s: Sensor) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<CameraForm>(() => emptyCamera(camera));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const feedLabel = FEED_TYPES.find((t) => t.id === camera.feed_type)?.label ?? camera.feed_type;

  const save = async () => {
    setError("");
    const r = cameraInput(form, false);
    if (typeof r === "string") return setError(r);
    setSaving(true);
    try {
      onChanged(await sensorsApi.update(sensor.id, { camera: r }));
      setEditing(false);
    } catch (e) {
      setError(errText(e, "Could not save the camera settings"));
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <div className="space-y-4">
        <CameraFields value={form} onChange={setForm} editing />
        {error && <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-500">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className={btnCls} onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
          <button type="button" className={primaryCls} onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</button>
        </div>
      </div>
    );
  }

  const rows: [string, string][] = camera.feed_type === "rtsp"
    ? [
        ["Type", feedLabel],
        ["Make", BRANDS.find((b) => b.id === camera.brand)?.label ?? camera.brand ?? ""],
        ["Address", `${camera.host}:${camera.port}`],
        ["Login", camera.username ? `${camera.username} · ${camera.has_password ? "password saved" : "no password"}` : "none"],
        ["Stream", camera.path ?? ""],
        ["Location", camera.lat != null && camera.lon != null ? `${camera.lat}, ${camera.lon}` : "not set"],
      ]
    : [
        ["Type", feedLabel],
        ["URL", camera.url ?? ""],
        ...(camera.feed_type === "snapshot" ? [["Refresh", `every ${camera.interval_s ?? 2}s`] as [string, string]] : []),
        ["Login", camera.username ? `${camera.username} · ${camera.has_password ? "password saved" : "no password"}` : "none"],
        ["Location", camera.lat != null && camera.lon != null ? `${camera.lat}, ${camera.lon}` : "not set"],
      ];

  return (
    <div className="space-y-4">
      <LiveVideo sensor={sensor} />
      {streamError && sensor.status !== "live" && (
        <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-500">
          No video yet: {streamError}.
        </p>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-foreground font-mono text-xs self-center min-w-0 truncate">{v}</dd>
          </div>
        ))}
      </dl>
      <ol className="space-y-2.5">
        <Step n={1}>Make sure the sensor hub runs somewhere that can reach this {camera.feed_type === "rtsp" ? "camera" : "address"}.</Step>
        <Step n={2}>The hub connects within about 10 seconds. This page turns <b>Live</b> once video arrives.</Step>
        <Step n={3}>To get alerts, open the sensor in the list and turn on <b>Alert watch</b>.</Step>
      </ol>
      <button type="button" className={btnCls} onClick={() => { setForm(emptyCamera(camera)); setEditing(true); }}>
        <Pencil className="w-3.5 h-3.5" /> Edit connection
      </button>
    </div>
  );
}
function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-3 text-sm text-foreground">
      <span className="w-5 h-5 shrink-0 rounded-full bg-secondary text-[11px] font-semibold grid place-items-center text-muted-foreground">
        {n}
      </span>
      <span className="min-w-0">{children}</span>
    </li>
  );
}

function SetupView({ sensor, onBack, onChanged }: { sensor: Sensor; onBack: () => void; onChanged: (s: Sensor) => void }) {
  const setup = sensor.setup;
  const [busy, setBusy] = useState(false);
  const connected = sensor.status === "live";

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <button type="button" className={btnCls} onClick={onBack}>
          <ArrowLeft className="w-3.5 h-3.5" /> All sensors
        </button>
        <span className="ml-auto"><StatusPill status={sensor.status} /></span>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-foreground">Connect “{sensor.name}”</h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          {connected ? "Connected — data is coming in." : "This page updates by itself once the first data arrives."}
        </p>
      </div>

      {!setup?.hub_reachable && (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-600">
          The sensor hub is not reachable from SoldierIQ, so connection details are missing. Start the sensor hub and reopen this page.
        </p>
      )}

      {sensor.sensor_type === "phone" && setup?.pair_url && (
        <div className="grid grid-cols-[minmax(0,1fr)] sm:grid-cols-[auto_minmax(0,1fr)] gap-5 items-start">
          <div className="p-3 rounded-xl bg-white justify-self-center">
            <QRCodeSVG value={setup.pair_url} size={176} />
          </div>
          {isLanHub(setup.pair_url) ? (
            <ol className="space-y-2.5 min-w-0">
              <Step n={1}>Connect the phone to the same network as the sensor hub.</Step>
              <Step n={2}>Scan this QR code with the phone&apos;s camera app and open the link.</Step>
              <Step n={3}>
                The phone warns about the certificate (self-signed). On iPhone tap <b>Show Details → visit this website</b>; on
                Android <b>Advanced → Proceed</b>.
              </Step>
              <Step n={4}>Tap <b>Start sensor</b> and allow camera, location and motion access. Keep the screen on.</Step>
            </ol>
          ) : (
            <ol className="space-y-2.5 min-w-0">
              <Step n={1}>Scan this QR code with the phone&apos;s camera app and open the link. Any network works (Wi-Fi or mobile data).</Step>
              <Step n={2}>Tap <b>Start sensor</b> and allow camera, location and motion access.</Step>
              <Step n={3}>Keep the screen on and the page open while it streams.</Step>
            </ol>
          )}
          <div className="sm:col-span-2 space-y-2 min-w-0">
            <CopyField label="Pairing link" value={setup.pair_url} />
            <div className="flex items-center gap-2">
              <p className={`${hintCls} !mt-0 flex-1`}>Anyone with this link can stream as this sensor. Make a new one if it leaks.</p>
              <button
                type="button"
                className={btnCls}
                disabled={busy}
                onClick={async () => {
                  if (!confirm("Make a new pairing link? The current one stops working and the phone disconnects.")) return;
                  setBusy(true);
                  try {
                    onChanged(await sensorsApi.newPairing(sensor.id));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <RefreshCw className="w-3.5 h-3.5" /> New link
              </button>
            </div>
          </div>
        </div>
      )}

      {sensor.sensor_type === "ip_camera" && setup?.camera && (
        <CameraSetup sensor={sensor} camera={setup.camera} streamError={setup.stream_error} onChanged={onChanged} />
      )}

      {sensor.sensor_type === "gps_tracker" && setup && (
        <div className="space-y-4">
          <div className="grid grid-cols-[minmax(0,1fr)] sm:grid-cols-2 gap-3">
            <CopyField label="Server address" value={setup.server_host || "—"} />
            <CopyField label="Port" value={String(setup.server_port ?? "")} />
            <div className="sm:col-span-2">
              <CopyField label="Device ID" value={setup.device_id || ""} />
            </div>
          </div>
          <div className="rounded-xl border border-border p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2.5">Phone with Traccar Client app</div>
            <ol className="space-y-2.5">
              <Step n={1}>Install <b>Traccar Client</b> from the App Store or Google Play.</Step>
              <Step n={2}>
                Set <b>Server URL</b> to <code className="font-mono text-xs">{setup.server_url || "—"}</code> and{" "}
                <b>Device identifier</b> to <code className="font-mono text-xs">{setup.device_id}</code>.
              </Step>
              <Step n={3}>Set location accuracy to <b>High</b> and the interval to about <b>10 seconds</b>.</Step>
              <Step n={4}>Turn tracking <b>on</b> and allow location access (“Always”).</Step>
            </ol>
          </div>
          <div className="rounded-xl border border-border p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Hardware GPS tracker</div>
            {setup.tcp_endpoint ? (
              <p className="text-sm text-foreground">
                Configure the tracker (usually by SMS or the maker&apos;s setup tool) to send to{" "}
                <code className="font-mono text-xs">{setup.tcp_endpoint}</code>. The device ID must match its IMEI.
              </p>
            ) : (
              <p className="text-sm text-foreground">
                Configure the tracker (usually by SMS or the maker&apos;s setup tool) to send to the server address above on the
                port for its protocol (for example Teltonika 5027, GT06/Concox 5023, OsmAnd 5055). The device ID must match its
                IMEI.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function SensorsPanel() {
  const [sensors, setSensors] = useState<Sensor[] | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [view, setView] = useState<View>({ kind: "list" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const loading = useRef(false);

  const load = useCallback(async () => {
    if (loading.current) return;
    loading.current = true;
    try {
      const r = await sensorsApi.list();
      setSensors(r.sensors);
      setIsAdmin(r.is_admin);
      setError("");
    } catch (e) {
      setError(errText(e, "Could not load sensors"));
      setSensors((s) => s ?? []);
    } finally {
      loading.current = false;
    }
  }, []);

  // Live status: refresh every 3 s while the tab is open.
  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  const upsert = (s: Sensor) => setSensors((list) => (list ? [...list.filter((x) => x.id !== s.id), s] : [s]));

  if (sensors === null) return <p className="text-sm text-muted-foreground">Loading sensors…</p>;

  if (view.kind === "add") {
    return (
      <AddSensor
        onCancel={() => setView({ kind: "list" })}
        onCreated={(s) => {
          upsert(s);
          setView({ kind: "setup", id: s.id });
        }}
      />
    );
  }

  if (view.kind === "setup") {
    const s = sensors.find((x) => x.id === view.id);
    if (s) return <SetupView sensor={s} onBack={() => setView({ kind: "list" })} onChanged={upsert} />;
  }

  const live = sensors.filter((s) => s.status === "live").length;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <p className="text-xs text-muted-foreground flex-1">
          {sensors.length === 0
            ? "No sensors yet."
            : `${sensors.length} sensor${sensors.length === 1 ? "" : "s"} · ${live} live`}
        </p>
        {isAdmin && (
          <button type="button" className={primaryCls} onClick={() => setView({ kind: "add" })}>
            <Plus className="w-3.5 h-3.5" /> Add sensor
          </button>
        )}
      </div>

      {error && <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-500">{error}</p>}
      {notice && (
        <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-500">{notice}</p>
      )}

      {sensors.length === 0 && !error && (
        <div className="rounded-xl border border-dashed border-border px-6 py-10 text-center">
          <Smartphone className="w-6 h-6 mx-auto text-muted-foreground" />
          <p className="text-sm text-foreground mt-2">Add a phone or GPS tracker as a live sensor.</p>
          <p className="text-xs text-muted-foreground mt-1">
            {isAdmin ? "Its camera, location and heading will flow into SoldierIQ." : "Ask an organization admin to add sensors."}
          </p>
        </div>
      )}

      <RecentAlerts />

      <div className="space-y-2">
        {sensors.map((s) => (
          <SensorRow
            key={s.id}
            sensor={s}
            isAdmin={isAdmin}
            onSetup={() => setView({ kind: "setup", id: s.id })}
            onChanged={(msg) => {
              setNotice(msg || "");
              load();
            }}
          />
        ))}
      </div>
    </div>
  );
}
