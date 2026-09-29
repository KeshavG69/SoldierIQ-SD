"use client";

/**
 * Connectors — connect third-party apps (Composio) and choose which of each
 * app's actions the chat agent may use (mirrors enterprise's actions tab).
 *
 *   - Connect opens Composio's hosted OAuth flow in a popup (useConnectorPopup).
 *   - Each connected app has an on/off switch and an expandable list of its
 *     actions, each with its own switch. At most `limit` actions can be on.
 *   - Disconnect revokes the Composio account and switches the app off.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { connectorsApi, Connector, ConnectorAction, ConnectorsResponse } from "@/lib/api/connectors";
import { Z_INDEX } from "@/lib/constants/zIndex";
import { useAuthStore } from "@/lib/stores/authStore";
import { useConnectorPopup } from "@/lib/hooks/useConnectorPopup";

// Last list seen in this tab, per organization: reopening the modal shows it
// instantly while a fresh copy loads in the background.
let lastLoaded: { orgId: string; data: ConnectorsResponse } | null = null;

export default function ConnectorsModal({ onClose }: { onClose: () => void }) {
  const orgId = useAuthStore((s) => s.user?.organization_id) || "";
  const [data, setDataState] = useState<ConnectorsResponse | null>(
    lastLoaded?.orgId === orgId ? lastLoaded.data : null
  );
  const setData: typeof setDataState = (v) =>
    setDataState((prev) => {
      const next = typeof v === "function" ? (v as (p: ConnectorsResponse | null) => ConnectorsResponse | null)(prev) : v;
      lastLoaded = next ? { orgId, data: next } : null;
      return next;
    });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await connectorsApi.list();
      setData(res);
      return res;
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to load connectors.");
      return null;
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const { connect, connecting, error: connectError } = useConnectorPopup(async (service, ok) => {
    await load();
    if (ok) setExpanded(service);
  });
  const startConnect = useCallback((c: Connector) => connect(c.service), [connect]);

  const onDisconnect = useCallback(
    async (c: Connector) => {
      if (!confirm(`Disconnect ${c.name}? The assistant will no longer be able to use it.`)) return;
      setBusy(c.service);
      setError(null);
      try {
        await connectorsApi.disconnect(c.service);
        await load();
      } catch (e: any) {
        setError(e?.response?.data?.detail || e?.message || "Disconnect failed");
      } finally {
        setBusy(null);
      }
    },
    [load]
  );

  // Optimistic toggles mirroring the server rules (app off → its actions off;
  // action on → app on). Only re-sync from the server if a toggle fails
  // (e.g. the action limit), so a successful click costs one request.
  const onToggleTool = useCallback(
    async (c: Connector, enabled: boolean) => {
      setError(null);
      setData((d) =>
        d && {
          ...d,
          connectors: d.connectors.map((x) =>
            x.id !== c.id
              ? x
              : { ...x, enabled, actions: enabled ? x.actions : x.actions.map((a) => ({ ...a, enabled: false })) }
          ),
        }
      );
      try {
        await connectorsApi.toggleTool(c.id, enabled);
      } catch (e: any) {
        setError(e?.response?.data?.detail || "Failed to update app");
        load(); // roll the optimistic change back to the server's state
      }
    },
    [load]
  );

  const onToggleAction = useCallback(
    async (c: Connector, a: ConnectorAction, enabled: boolean) => {
      setError(null);
      setData((d) =>
        d && {
          ...d,
          total_enabled: d.total_enabled + (enabled ? 1 : -1),
          connectors: d.connectors.map((x) =>
            x.id !== c.id
              ? x
              : {
                  ...x,
                  enabled: enabled ? true : x.enabled,
                  actions: x.actions.map((y) => (y.id === a.id ? { ...y, enabled } : y)),
                }
          ),
        }
      );
      try {
        await connectorsApi.toggleAction(a.id, enabled);
      } catch (e: any) {
        setError(e?.response?.data?.detail || "Failed to update action");
        load(); // roll the optimistic change back to the server's state
      }
    },
    [load]
  );

  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      (data?.connectors || []).filter(
        (c) =>
          !q ||
          c.name.toLowerCase().includes(q) ||
          (c.category || "").toLowerCase().includes(q) ||
          (c.description || "").toLowerCase().includes(q)
      ),
    [data, q]
  );
  const connected = filtered.filter((c) => c.connected);
  const available = filtered.filter((c) => !c.connected);
  const atLimit = !!data && data.total_enabled >= data.limit;

  const row = (c: Connector) => (
    <ConnectorRow
      key={c.service}
      c={c}
      busy={busy === c.service || connecting === c.service}
      expanded={expanded === c.service}
      atLimit={atLimit}
      onExpand={() => setExpanded((s) => (s === c.service ? null : c.service))}
      onConnect={startConnect}
      onDisconnect={onDisconnect}
      onToggleTool={onToggleTool}
      onToggleAction={onToggleAction}
    />
  );

  return (
    <>
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" style={{ zIndex: Z_INDEX.MODAL }} onClick={onClose} />
      <div
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-2xl px-4"
        style={{ zIndex: Z_INDEX.MODAL + 1 }}
      >
        <div className="rounded-2xl bg-card border border-border shadow-2xl overflow-hidden max-h-[85vh] flex flex-col">
          <div className="px-6 py-4 border-b border-border flex items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold text-foreground">Connectors</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                Connect apps and choose which actions the assistant can use.
              </p>
            </div>
            <div className="flex items-center gap-3">
              {data && (
                <span
                  className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                    atLimit ? "bg-amber-500/15 text-amber-500" : "bg-secondary text-muted-foreground"
                  }`}
                >
                  {data.total_enabled}/{data.limit} actions enabled
                </span>
              )}
              <button onClick={onClose} className="p-1.5 rounded-md text-muted-foreground hover:bg-accent transition-colors" aria-label="Close">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
          </div>

          <div className="px-6 pt-4">
            <input
              className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15 transition-all"
              placeholder="Search apps"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div className="overflow-y-auto p-6 space-y-6">
            {(error || connectError) && <p className="text-xs text-red-500">{error || connectError}</p>}
            {atLimit && (
              <p className="text-xs text-amber-500">
                Maximum action limit reached. Disable an action to enable another.
              </p>
            )}

            {!data ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : (
              <>
                {connected.length > 0 && <Section title="Connected">{connected.map(row)}</Section>}
                <Section title="Available">
                  {available.length === 0 ? (
                    <p className="px-4 py-3 text-sm text-muted-foreground">No apps match “{query}”.</p>
                  ) : (
                    available.map(row)
                  )}
                </Section>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">{title}</h3>
      <div className="rounded-xl border border-border divide-y divide-border">{children}</div>
    </div>
  );
}

function Toggle({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        checked ? "bg-brand" : "bg-secondary"
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
          checked ? "translate-x-[18px]" : "translate-x-[3px]"
        }`}
      />
    </button>
  );
}

function ConnectorLogo({ c }: { c: Connector }) {
  const [failed, setFailed] = useState(false);
  // White tile in both themes: several brand marks (GitHub, Notion) are black.
  return (
    <div className="w-9 h-9 shrink-0 rounded-lg bg-white border border-border flex items-center justify-center overflow-hidden">
      {c.logo && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={c.logo} alt={`${c.name} logo`} className="w-6 h-6 object-contain" onError={() => setFailed(true)} />
      ) : (
        <span className="text-xs font-semibold text-neutral-700">{c.name.charAt(0).toUpperCase()}</span>
      )}
    </div>
  );
}

function ConnectorRow({
  c,
  busy,
  expanded,
  atLimit,
  onExpand,
  onConnect,
  onDisconnect,
  onToggleTool,
  onToggleAction,
}: {
  c: Connector;
  busy: boolean;
  expanded: boolean;
  atLimit: boolean;
  onExpand: () => void;
  onConnect: (c: Connector) => void;
  onDisconnect: (c: Connector) => void;
  onToggleTool: (c: Connector, enabled: boolean) => void;
  onToggleAction: (c: Connector, a: ConnectorAction, enabled: boolean) => void;
}) {
  const enabledCount = c.actions.filter((a) => a.enabled).length;

  return (
    <div>
      <div className="flex items-center gap-3 px-4 py-3">
        <ConnectorLogo c={c} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-foreground truncate">{c.name}</span>
            {c.category && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-secondary text-muted-foreground">
                {c.category}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground truncate">
            {c.connected ? (
              <>
                <span className="text-emerald-500">Connected</span>
                {" · "}
                {enabledCount}/{c.actions.length} actions enabled
              </>
            ) : (
              c.description
            )}
          </p>
        </div>

        {c.connected ? (
          <>
            <Toggle checked={c.enabled} onChange={(v) => onToggleTool(c, v)} label={`Enable ${c.name}`} />
            <button
              onClick={onExpand}
              className="p-1.5 rounded-md text-muted-foreground hover:bg-accent transition-colors"
              aria-label={expanded ? `Hide ${c.name} actions` : `Show ${c.name} actions`}
              aria-expanded={expanded}
            >
              <svg
                className={`w-4 h-4 transition-transform ${expanded ? "rotate-180" : ""}`}
                viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
          </>
        ) : (
          <button
            onClick={() => onConnect(c)}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg bg-brand text-brand-foreground text-xs font-medium hover:bg-brand-hover disabled:opacity-50 transition-colors"
          >
            {busy ? "Connecting…" : "Connect"}
          </button>
        )}
      </div>

      {c.connected && expanded && (
        <div className="px-4 pb-3">
          <div className="rounded-lg border border-border bg-surface-2/50 divide-y divide-border">
            {c.actions.map((a) => (
              <div key={a.id} className="flex items-start gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-foreground">{a.title}</span>
                    <span
                      className={`px-1.5 py-px rounded text-[9px] font-semibold uppercase tracking-wide ${
                        a.type === "write" ? "bg-amber-500/15 text-amber-500" : "bg-blue-500/15 text-blue-500"
                      }`}
                    >
                      {a.type}
                    </span>
                  </div>
                  {a.description && (
                    <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2">{a.description}</p>
                  )}
                </div>
                <Toggle
                  checked={a.enabled}
                  disabled={!a.enabled && atLimit}
                  onChange={(v) => onToggleAction(c, a, v)}
                  label={`Enable ${a.title}`}
                />
              </div>
            ))}
          </div>
          <div className="flex justify-end mt-2">
            <button
              onClick={() => onDisconnect(c)}
              disabled={busy}
              className="px-3 py-1.5 rounded-lg text-xs font-medium text-muted-foreground border border-border hover:text-red-500 hover:border-red-500/40 disabled:opacity-50 transition-colors"
            >
              {busy ? "Disconnecting…" : `Disconnect ${c.name}`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
