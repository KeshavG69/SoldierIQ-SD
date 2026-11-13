"use client";

/**
 * TAK (Team Awareness Kit) settings — the "TAK" tab of the Connectors modal.
 * Loads the saved config on mount, saves/deletes it via /api/tak/config and
 * mirrors the result into the chat store so chat requests carry TAK creds.
 */

import { useState, useEffect } from "react";
import { configureTAK, getTAKConfig, deleteTAKConfig } from "@/lib/api/tak";
import { useChatStore } from "@/lib/stores/chatStore";

const inputCls =
  "w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm font-mono text-foreground placeholder:text-muted-foreground placeholder:font-sans focus:outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15 transition-all";
const labelCls = "block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5";
const hintCls = "text-[11px] text-muted-foreground mt-1";

export default function TAKSettingsPanel({ onClose }: { onClose: () => void }) {
  const { setTAKCredentials, setTAKEnabled } = useChatStore();

  const [takEnabled, setLocalTAKEnabled] = useState(false);
  const [takHost, setTakHost] = useState("");
  const [takPort, setTakPort] = useState(8087);
  const [takUsername, setTakUsername] = useState("");
  const [takPassword, setTakPassword] = useState("");
  const [agentCallsign, setAgentCallsign] = useState("SoldierIQ-Agent");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Load the saved config when the tab opens.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = await getTAKConfig();
        if (cancelled) return;
        setLocalTAKEnabled(config.tak_enabled);
        setTakHost(config.tak_host);
        setTakPort(config.tak_port);
        setTakUsername(config.tak_username);
        setAgentCallsign(config.agent_callsign);
        // Password is not returned from backend for security
        setTakPassword("");
      } catch {
        // TAK not configured yet - expected on first load; show empty form
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async () => {
    setError("");
    setSuccess("");

    if (takEnabled) {
      if (!takHost.trim()) {
        setError("TAK Host is required");
        return;
      }
      if (!takPort || takPort < 1 || takPort > 65535) {
        setError("Valid TAK Port is required (1-65535)");
        return;
      }
      // Username and password are optional for public servers
    }

    setIsSaving(true);
    try {
      const config = await configureTAK({
        tak_enabled: takEnabled,
        tak_host: takHost.trim(),
        tak_port: takPort,
        tak_username: takUsername.trim(),
        tak_password: takPassword.trim(),
        agent_callsign: agentCallsign.trim(),
      });

      // Store password in localStorage for chat integration (can be empty for public servers)
      if (takEnabled) {
        if (takPassword) {
          localStorage.setItem("tak_password", takPassword);
        } else {
          localStorage.removeItem("tak_password");
        }
        setTAKCredentials({
          tak_host: config.tak_host,
          tak_port: config.tak_port,
          tak_username: config.tak_username,
          tak_password: takPassword,
          agent_callsign: config.agent_callsign,
        });
        setTAKEnabled(true);
      } else {
        localStorage.removeItem("tak_password");
        setTAKCredentials(null);
        setTAKEnabled(false);
      }

      setSuccess("TAK configuration saved successfully!");
      setTimeout(onClose, 1500);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || "Failed to save TAK configuration");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm("Are you sure you want to delete the TAK configuration?")) return;

    setIsSaving(true);
    setError("");
    try {
      await deleteTAKConfig();
      localStorage.removeItem("tak_password");
      setTAKCredentials(null);
      setTAKEnabled(false);
      setSuccess("TAK configuration deleted successfully!");
      setTimeout(onClose, 1500);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || "Failed to delete TAK configuration");
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading configuration…</p>;
  }

  return (
    <div className="space-y-5">
      {/* Enable toggle */}
      <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-foreground">Enable TAK integration</div>
          <p className="text-xs text-muted-foreground">Allow the AI agent to interact with the TAK network.</p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={takEnabled}
          aria-label="Enable TAK integration"
          onClick={() => setLocalTAKEnabled(!takEnabled)}
          className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
            takEnabled ? "bg-brand" : "bg-secondary"
          }`}
        >
          <span
            className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
              takEnabled ? "translate-x-[18px]" : "translate-x-[3px]"
            }`}
          />
        </button>
      </div>

      {takEnabled && (
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_8rem] gap-4">
          <div>
            <label htmlFor="tak-host" className={labelCls}>TAK host *</label>
            <input
              id="tak-host"
              type="text"
              value={takHost}
              onChange={(e) => setTakHost(e.target.value)}
              placeholder="e.g. tak.company.com or 192.168.1.100"
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="tak-port" className={labelCls}>Port *</label>
            <input
              id="tak-port"
              type="number"
              value={takPort}
              onChange={(e) => setTakPort(parseInt(e.target.value) || 8087)}
              min="1"
              max="65535"
              className={inputCls}
            />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="tak-username" className={labelCls}>Username</label>
            <input
              id="tak-username"
              type="text"
              value={takUsername}
              onChange={(e) => setTakUsername(e.target.value)}
              placeholder="e.g. soldieriq-agent"
              autoComplete="off"
              className={inputCls}
            />
            <p className={hintCls}>Optional — leave empty for public servers.</p>
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="tak-password" className={labelCls}>Password</label>
            <input
              id="tak-password"
              type="password"
              value={takPassword}
              onChange={(e) => setTakPassword(e.target.value)}
              placeholder="TAK server password (optional)"
              autoComplete="new-password"
              className={inputCls}
            />
            <p className={hintCls}>Optional — stored locally for chat integration.</p>
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="tak-callsign" className={labelCls}>Agent callsign</label>
            <input
              id="tak-callsign"
              type="text"
              value={agentCallsign}
              onChange={(e) => setAgentCallsign(e.target.value)}
              placeholder="SoldierIQ-Agent"
              className={inputCls}
            />
            <p className={hintCls}>Identifier shown on the TAK network for the AI agent.</p>
          </div>
        </div>
      )}

      {error && (
        <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-500">{error}</p>
      )}
      {success && (
        <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-500">
          {success}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
        {takHost && (
          <button
            onClick={handleDelete}
            disabled={isSaving}
            className="mr-auto px-3 py-1.5 rounded-lg text-xs font-medium text-muted-foreground border border-border hover:text-red-500 hover:border-red-500/40 disabled:opacity-50 transition-colors"
          >
            Delete configuration
          </button>
        )}
        <button
          onClick={onClose}
          disabled={isSaving}
          className="px-3 py-1.5 rounded-lg text-xs font-medium text-muted-foreground border border-border hover:bg-accent disabled:opacity-50 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="px-3 py-1.5 rounded-lg bg-brand text-brand-foreground text-xs font-medium hover:bg-brand-hover disabled:opacity-50 transition-colors"
        >
          {isSaving ? "Saving…" : "Save configuration"}
        </button>
      </div>
    </div>
  );
}
