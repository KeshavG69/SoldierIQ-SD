"use client";

/**
 * Camera alerts (decision model) UI:
 *   - AlertWatchEditor: per camera, what to alert on (Person, Vehicle, Bird, anything typed) + on/off
 *   - DetectionReadout: what the decision model currently sees (live probabilities)
 *   - RecentAlerts: list of alerts with the frame that triggered them
 *   - SensorAlertToaster: pop-ups anywhere in SoldierIQ when a new alert arrives
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, BellOff, Check, Plus, X } from "lucide-react";
import { sensorsApi, Sensor, SensorAlert, WatchConfig, WatchRule } from "@/lib/api/sensors";
import { Z_INDEX } from "@/lib/constants/zIndex";

const SUGGESTIONS: WatchRule[] = [
  { label: "Person", question: "Is at least one person visible?" },
  { label: "Vehicle", question: "Is a car, truck, motorcycle or other vehicle visible?" },
  { label: "Weapon", question: "Is a gun, knife or other weapon visible?" },
  { label: "Drone / aircraft", question: "Is a drone or small aircraft visible?" },
  { label: "Fire / smoke", question: "Is fire or smoke visible?" },
  { label: "Animal", question: "Is an animal visible?" },
  { label: "Bird", question: "Is a bird visible?" },
  { label: "Open door / gate", question: "Is a door or gate open?" },
];

const chip =
  "inline-flex items-center gap-1 pl-2.5 pr-1.5 py-1 rounded-full text-[12px] border border-border bg-secondary/60 text-foreground";
const btn =
  "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[12px] font-medium border border-border text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50 transition-colors";

export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 10) return "just now";
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(iso).toLocaleString();
}

export function AlertWatchEditor({ sensor, isAdmin, onSaved }: { sensor: Sensor; isAdmin: boolean; onSaved: () => void }) {
  const saved: WatchConfig = sensor.watch || { enabled: false, rules: [] };
  const [watch, setWatch] = useState<WatchConfig>(saved);
  const [label, setLabel] = useState("");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Compare what the user chooses (on/off + which things), not server-filled defaults like the question text.
  const key = (w: WatchConfig) => JSON.stringify([w.enabled, w.rules.map((r) => r.label.toLowerCase()).sort()]);
  const dirty = key(watch) !== key(saved);

  const save = async (next: WatchConfig) => {
    setBusy(true);
    setError("");
    try {
      const s = await sensorsApi.update(sensor.id, { watch: next });
      setWatch(s.watch || next);
      onSaved();
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Could not save");
    } finally {
      setBusy(false);
    }
  };

  const addRule = (r: WatchRule) => {
    if (!r.label.trim() || watch.rules.some((x) => x.label.toLowerCase() === r.label.trim().toLowerCase())) return;
    setWatch({ ...watch, rules: [...watch.rules, { label: r.label.trim(), question: r.question?.trim() || undefined }] });
    setLabel("");
    setQuestion("");
  };
  const unused = SUGGESTIONS.filter((s) => !watch.rules.some((r) => r.label.toLowerCase() === s.label.toLowerCase()));

  return (
    <div className="rounded-lg border border-border p-3 space-y-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium text-foreground flex items-center gap-1.5">
            {watch.enabled ? <Bell className="w-3.5 h-3.5 text-brand" /> : <BellOff className="w-3.5 h-3.5 text-muted-foreground" />}
            Camera alerts
          </div>
          <p className="text-[11px] text-muted-foreground">
            A decision model checks the camera every {watch.interval_s ?? 3}s and alerts when it sees what you choose.
          </p>
        </div>
        {isAdmin && (
          <button
            type="button"
            role="switch"
            aria-checked={watch.enabled}
            aria-label="Camera alerts on/off"
            disabled={busy}
            onClick={() => save({ ...watch, enabled: !watch.enabled })}
            className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${watch.enabled ? "bg-brand" : "bg-secondary"}`}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${watch.enabled ? "translate-x-[18px]" : "translate-x-[3px]"}`} />
          </button>
        )}
      </div>

      <div>
        <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Alert when it sees</div>
        <div className="flex flex-wrap gap-1.5">
          {watch.rules.length === 0 && <span className="text-[12px] text-muted-foreground">Nothing yet.</span>}
          {watch.rules.map((r) => (
            <span key={r.label} className={chip} title={r.question}>
              {r.label}
              {isAdmin && (
                <button
                  type="button"
                  aria-label={`Stop alerting on ${r.label}`}
                  className="rounded-full p-0.5 text-muted-foreground hover:text-red-500"
                  onClick={() => setWatch({ ...watch, rules: watch.rules.filter((x) => x.label !== r.label) })}
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </span>
          ))}
        </div>
      </div>

      {isAdmin && (
        <>
          {unused.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {unused.map((s) => (
                <button key={s.label} type="button" className={btn} onClick={() => addRule(s)}>
                  <Plus className="w-3 h-3" /> {s.label}
                </button>
              ))}
            </div>
          )}
          <div className="grid sm:grid-cols-[1fr_1.6fr_auto] gap-2">
            <input
              className="px-2.5 py-1.5 rounded-lg bg-surface-2 border border-border text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/60"
              placeholder="Something else, e.g. Dog"
              value={label}
              maxLength={40}
              onChange={(e) => setLabel(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addRule({ label, question })}
            />
            <input
              className="px-2.5 py-1.5 rounded-lg bg-surface-2 border border-border text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/60"
              placeholder="Optional exact question, e.g. Is a dog inside the fence?"
              value={question}
              maxLength={200}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addRule({ label, question })}
            />
            <button type="button" className={btn} disabled={!label.trim()} onClick={() => addRule({ label, question })}>
              <Plus className="w-3 h-3" /> Add
            </button>
          </div>
          {(dirty || error) && (
            <div className="flex items-center gap-2">
              {error && <span className="text-[12px] text-red-500 flex-1">{error}</span>}
              {dirty && (
                <>
                  <span className="text-[12px] text-muted-foreground flex-1">Unsaved changes</span>
                  <button type="button" className={btn} onClick={() => setWatch(saved)} disabled={busy}>Undo</button>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-brand text-brand-foreground text-[12px] font-medium hover:bg-brand-hover disabled:opacity-50"
                    onClick={() => save(watch)}
                    disabled={busy}
                  >
                    <Check className="w-3 h-3" /> Save
                  </button>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function DetectionReadout({ sensor }: { sensor: Sensor }) {
  const d = sensor.latest.detection;
  if (!sensor.watch?.enabled || !d || sensor.status !== "live") return null;
  const age = (Date.now() - d.received_ts) / 1000;
  if (age > 30) return null;
  const items = Object.entries(d.data.probabilities).sort((a, b) => b[1] - a[1]);
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11.5px]">
      <span className="text-muted-foreground">Sees now:</span>
      {items.map(([label, p]) => (
        <span
          key={label}
          className={`px-1.5 py-0.5 rounded tabular-nums ${p >= 0.85 ? "bg-red-500/15 text-red-500 font-semibold" : "bg-secondary text-muted-foreground"}`}
        >
          {label} {Math.round(p * 100)}%
        </span>
      ))}
    </div>
  );
}

function AlertItem({ a, onAck }: { a: SensorAlert; onAck: () => void }) {
  return (
    <div className={`flex gap-3 rounded-lg border p-2 ${a.acknowledged ? "border-border opacity-70" : "border-red-500/40 bg-red-500/5"}`}>
      <a href={a.image_url} target="_blank" rel="noreferrer" className="shrink-0">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={a.image_url} alt={`${a.label} at ${a.sensor_name}`} className="w-20 h-14 object-cover rounded bg-black" />
      </a>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold text-foreground truncate">
          {a.label} <span className="font-normal text-muted-foreground">· {a.sensor_name}</span>
        </div>
        <div className="text-[11.5px] text-muted-foreground">
          {timeAgo(a.created_at)} · {Math.round(a.probability * 100)}% sure
          {a.lat != null && a.lon != null && (
            <>
              {" · "}
              <a
                className="text-brand hover:underline"
                href={`https://www.openstreetmap.org/?mlat=${a.lat}&mlon=${a.lon}#map=17/${a.lat}/${a.lon}`}
                target="_blank"
                rel="noreferrer"
              >
                map
              </a>
            </>
          )}
        </div>
      </div>
      {!a.acknowledged && (
        <button type="button" className={`${btn} self-center`} onClick={onAck}>
          <Check className="w-3 h-3" /> Seen
        </button>
      )}
    </div>
  );
}

export function RecentAlerts() {
  const [alerts, setAlerts] = useState<SensorAlert[] | null>(null);
  const load = useCallback(async () => {
    try {
      setAlerts((await sensorsApi.alerts({ limit: 8 })).alerts);
    } catch {
      setAlerts((a) => a ?? []);
    }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);
  if (!alerts || alerts.length === 0) return null;
  const open = alerts.filter((a) => !a.acknowledged).length;
  return (
    <div className="space-y-2">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Recent alerts {open > 0 && <span className="ml-1 px-1.5 py-0.5 rounded-full bg-red-500/15 text-red-500 normal-case">{open} new</span>}
      </div>
      {alerts.map((a) => (
        <AlertItem key={a.id} a={a} onAck={() => sensorsApi.acknowledge(a.id).then(load)} />
      ))}
    </div>
  );
}

/** New alerts pop up wherever the user is in SoldierIQ. Polls every 4 s; shows up to 3 at once. */
export function SensorAlertToaster() {
  const [toasts, setToasts] = useState<SensorAlert[]>([]);
  const since = useRef<string | null>(null);
  const disabled = useRef(false);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      if (disabled.current) return;
      try {
        if (since.current === null) {
          since.current = (await sensorsApi.alerts({ limit: 1 })).server_time; // only alerts from now on
          return;
        }
        const r = await sensorsApi.alerts({ since: since.current, limit: 10 });
        if (stop) return;
        if (r.alerts.length) {
          since.current = r.alerts[0].created_at;
          setToasts((t) => [...r.alerts.filter((a) => !a.acknowledged).reverse(), ...t].slice(0, 3));
        }
      } catch (e: any) {
        if (e?.response?.status === 503) disabled.current = true; // sensors not configured on this server
      }
    };
    tick();
    const t = setInterval(tick, 4000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, []);

  if (!toasts.length) return null;
  return (
    <div className="fixed top-16 right-4 flex flex-col gap-2 w-[340px] max-w-[calc(100vw-2rem)]" style={{ zIndex: Z_INDEX.TOAST }} role="status" aria-live="polite">
      {toasts.map((a) => (
        <div key={a.id} className="rounded-xl border border-red-500/50 bg-card shadow-2xl overflow-hidden">
          <div className="flex gap-3 p-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={a.image_url} alt={`${a.label} at ${a.sensor_name}`} className="w-24 h-16 object-cover rounded bg-black shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-red-500 flex items-center gap-1">
                <Bell className="w-3 h-3" /> Camera alert
              </div>
              <div className="text-[14px] font-semibold text-foreground truncate">{a.label}</div>
              <div className="text-[12px] text-muted-foreground truncate">
                {a.sensor_name} · {Math.round(a.probability * 100)}% sure · {timeAgo(a.created_at)}
              </div>
            </div>
            <button
              type="button"
              aria-label="Dismiss alert"
              className="self-start p-1 rounded text-muted-foreground hover:bg-accent"
              onClick={() => setToasts((t) => t.filter((x) => x.id !== a.id))}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="flex border-t border-border">
            <button
              type="button"
              className="flex-1 py-1.5 text-[12px] font-medium text-foreground hover:bg-accent"
              onClick={() => {
                sensorsApi.acknowledge(a.id).catch(() => {});
                setToasts((t) => t.filter((x) => x.id !== a.id));
              }}
            >
              Mark as seen
            </button>
            <a href={a.image_url} target="_blank" rel="noreferrer" className="flex-1 py-1.5 text-center text-[12px] font-medium text-brand hover:bg-accent border-l border-border">
              Open image
            </a>
          </div>
        </div>
      ))}
    </div>
  );
}
