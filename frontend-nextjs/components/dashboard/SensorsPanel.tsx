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
  ArrowLeft, Check, ChevronDown, Copy, MapPin, Pause, Pencil, Play, Plus, QrCode, RefreshCw, Smartphone, Trash2,
} from "lucide-react";
import { sensorsApi, Sensor, SensorType } from "@/lib/api/sensors";
import { AlertWatchEditor, DetectionReadout, RecentAlerts } from "./SensorAlerts";

const inputCls =
  "w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15 transition-all";
const labelCls = "block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5";
const hintCls = "text-[11px] text-muted-foreground mt-1";
const btnCls =
  "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50 transition-colors";
const primaryCls =
  "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand text-brand-foreground text-xs font-medium hover:bg-brand-hover disabled:opacity-50 transition-colors";

const TYPE_LABEL: Record<SensorType, string> = { phone: "Phone", gps_tracker: "GPS tracker" };

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
  const Icon = sensor.sensor_type === "phone" ? Smartphone : MapPin;

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
                <QrCode className="w-3.5 h-3.5" /> {sensor.sensor_type === "phone" ? "Pairing QR" : "Setup details"}
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
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    if (!name.trim()) return setError("Give the sensor a name, e.g. “North gate camera”.");
    setSaving(true);
    try {
      const s = await sensorsApi.create({
        name: name.trim(),
        sensor_type: type,
        identifier: type === "gps_tracker" && identifier.trim() ? identifier.trim() : undefined,
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
    { id: "gps_tracker", title: "GPS tracker", body: "A GPS tracker, or a phone running the Traccar Client app.", Icon: MapPin },
  ];

  return (
    <div className="space-y-5">
      <button type="button" className={btnCls} onClick={onCancel}>
        <ArrowLeft className="w-3.5 h-3.5" /> Back
      </button>
      <div>
        <div className={labelCls}>Sensor type</div>
        <div className="grid sm:grid-cols-2 gap-2" role="radiogroup" aria-label="Sensor type">
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
          placeholder={type === "phone" ? "e.g. North gate camera" : "e.g. Patrol vehicle 2"}
          autoFocus
        />
      </div>
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
        <div className="grid sm:grid-cols-[auto_1fr] gap-5 items-start">
          <div className="p-3 rounded-xl bg-white justify-self-center">
            <QRCodeSVG value={setup.pair_url} size={176} />
          </div>
          <ol className="space-y-2.5">
            <Step n={1}>Connect the phone to the same network as the sensor hub.</Step>
            <Step n={2}>Scan this QR code with the phone&apos;s camera app and open the link.</Step>
            <Step n={3}>
              The phone warns about the certificate (self-signed). On iPhone tap <b>Show Details → visit this website</b>; on
              Android <b>Advanced → Proceed</b>.
            </Step>
            <Step n={4}>Tap <b>Start sensor</b> and allow camera, location and motion access. Keep the screen on.</Step>
          </ol>
          <div className="sm:col-span-2 space-y-2">
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

      {sensor.sensor_type === "gps_tracker" && setup && (
        <div className="space-y-4">
          <div className="grid sm:grid-cols-2 gap-3">
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
            <p className="text-sm text-foreground">
              Configure the tracker (usually by SMS or the maker&apos;s setup tool) to send to the server address above on the
              port for its protocol (for example Teltonika 5027, GT06/Concox 5023, OsmAnd 5055). The device ID must match its
              IMEI.
            </p>
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
