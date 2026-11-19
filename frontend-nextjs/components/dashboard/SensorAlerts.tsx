"use client";

/**
 * Camera alerts (decision model) UI:
 *   - AlertWatchEditor: per camera, what to alert on (Person, Vehicle, Bird, anything typed) + on/off
 *   - DetectionReadout: what the decision model currently sees (live probabilities)
 *   - RecentAlerts: list of alerts with the frame that triggered them
 *   - SensorAlertToaster: pop-ups anywhere in SoldierIQ when a new alert arrives
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, BellOff, Bot, Check, Loader2, Plus, X } from "lucide-react";
import { AlertAssessment, sensorsApi, Sensor, SensorAlert, WatchConfig, WatchRule } from "@/lib/api/sensors";
import { Z_INDEX } from "@/lib/constants/zIndex";
import { useChatStore } from "@/lib/stores/chatStore";

const CHAT_WAIT_MS = 5 * 60 * 1000; // give up on posting an alert to the chat if its review never lands

/** Put a reviewed alert in the chat as a SoldierIQ message. False = not now (a reply is streaming). */
function postAlertToChat(a: SensorAlert): boolean {
  const chat = useChatStore.getState();
  const id = `alert-${a.id}`;
  if (chat.messages.some((m) => m.id === id)) return true; // already there (store persists across reloads)
  if (chat.isLoading) return false; // the stream writes into the last message: don't slip in under it
  const x = a.assessment;
  const reviewed = x?.status === "done" && !!x.text;
  chat.addMessage({
    id,
    role: "assistant",
    content: reviewed ? x!.text! : "I couldn't review this alert's image. Ask me to look at it.",
    timestamp: new Date().toISOString(),
    alert: {
      id: a.id, label: a.label, sensorName: a.sensor_name, probability: a.probability,
      imageUrl: a.image_url, createdAt: a.created_at, threat: reviewed ? x!.threat : null, reviewed,
    },
  });
  return true;
}

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
  const key = (w: WatchConfig) =>
    JSON.stringify([w.enabled, w.interval_s ?? 3, w.motion_only !== false, w.rules.map((r) => r.label.toLowerCase()).sort()]);
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
            A decision model checks the camera every {watch.interval_s ?? 3}s
            {watch.motion_only !== false ? " when something moves" : ""} and alerts when it sees what you choose.
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
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px]">
            <label className="inline-flex items-center gap-2 text-muted-foreground">
              Check every
              <select
                className="px-2 py-1 rounded-lg bg-surface-2 border border-border text-foreground"
                value={watch.interval_s ?? 3}
                onChange={(e) => setWatch({ ...watch, interval_s: Number(e.target.value) })}
              >
                {[2, 3, 5, 10, 30].map((n) => (
                  <option key={n} value={n}>{n} seconds</option>
                ))}
              </select>
            </label>
            <label className="inline-flex items-center gap-2 text-muted-foreground cursor-pointer" title="Skips the AI check when the picture hasn't changed. A check still runs once a minute.">
              <input
                type="checkbox"
                checked={watch.motion_only !== false}
                onChange={(e) => setWatch({ ...watch, motion_only: e.target.checked })}
              />
              Only check when something moves (saves cost)
            </label>
          </div>
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

export const THREAT_STYLE: Record<string, string> = {
  high: "bg-red-500/15 text-red-500",
  medium: "bg-amber-500/15 text-amber-600",
  low: "bg-emerald-500/15 text-emerald-600",
};

/** What the SoldierIQ agent made of the alert frame (it reviews every alert by itself). */
function AgentAssessment({ x, clamp }: { x: AlertAssessment | null; clamp?: boolean }) {
  if (!x || x.status === "skipped") return null;
  if (x.status === "reviewing")
    return (
      <div className="mt-1 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
        <Loader2 className="w-3 h-3 animate-spin" /> SoldierIQ is reviewing the image…
      </div>
    );
  if (x.status === "failed")
    return <div className="mt-1 text-[11.5px] text-muted-foreground">SoldierIQ couldn&apos;t review this alert.</div>;
  return (
    <div className="mt-1.5 text-[12px] leading-snug text-foreground">
      <span className="inline-flex items-center gap-1 mr-1.5 align-middle">
        <Bot className="w-3 h-3 text-muted-foreground" />
        {x.threat && (
          <span className={`px-1.5 py-px rounded text-[10px] font-semibold uppercase tracking-wide ${THREAT_STYLE[x.threat] ?? ""}`}>
            {x.threat}
          </span>
        )}
      </span>
      <span className={clamp ? "line-clamp-3" : "whitespace-pre-line"}>{x.text}</span>
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
        <AgentAssessment x={a.assessment} />
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
  const toastsRef = useRef<SensorAlert[]>([]);
  toastsRef.current = toasts;
  const since = useRef<string | null>(null);
  const disabled = useRef(false);
  const forChat = useRef(new Map<string, { a: SensorAlert; at: number }>()); // new alerts not yet in the chat

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
          for (const a of r.alerts) if (!forChat.current.has(a.id)) forChat.current.set(a.id, { a, at: Date.now() });
        }
        // The agent's review lands a few seconds after the alert: refresh the pop-ups (and the alerts still
        // waiting to go to the chat, even if their pop-up was closed) that are waiting for it.
        const waiting = new Set(toastsRef.current.filter((a) => a.assessment?.status === "reviewing").map((a) => a.id));
        for (const [id, p] of forChat.current) if (p.a.assessment?.status === "reviewing") waiting.add(id);
        if (waiting.size) {
          const ids = [...waiting].slice(0, 20);
          const fresh = (await sensorsApi.alerts({ ids: ids.join(","), limit: ids.length })).alerts;
          if (stop) return;
          const byId = new Map(fresh.map((a) => [a.id, a]));
          setToasts((t) => t.map((a) => byId.get(a.id) ?? a));
          for (const a of fresh) {
            const p = forChat.current.get(a.id);
            if (p) p.a = a;
          }
        }
        // Once the agent has reviewed an alert, its reaction goes into the chat (oldest first).
        const ready = [...forChat.current.values()].sort((x, y) => x.a.created_at.localeCompare(y.a.created_at));
        for (const p of ready) {
          const st = p.a.assessment?.status;
          if (st === "skipped") { forChat.current.delete(p.a.id); continue; } // a newer alert from that camera is reviewed instead
          const settled = st !== "reviewing" || Date.now() - p.at > CHAT_WAIT_MS;
          if (!settled) continue;
          if (!postAlertToChat(p.a)) break; // a reply is streaming: try again next tick, keep the order
          forChat.current.delete(p.a.id);
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
              <AgentAssessment x={a.assessment} clamp />
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
