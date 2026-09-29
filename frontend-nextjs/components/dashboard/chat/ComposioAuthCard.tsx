"use client";

/**
 * "Connect <app>" card under an assistant message, shown when the agent's
 * setup_composio_service tool reports the app isn't connected yet (port of
 * enterprise's ComposioAuthCard). Clicking starts a fresh Composio link in a
 * popup, so the card never holds an expiring auth URL.
 */

import { useState } from "react";
import { ComposioAuthInfo } from "@/types";
import { useConnectorPopup } from "@/lib/hooks/useConnectorPopup";

export default function ComposioAuthCard({ info }: { info: ComposioAuthInfo }) {
  const [connected, setConnected] = useState(info.already_connected);
  const [logoFailed, setLogoFailed] = useState(false);
  const { connect, connecting, error } = useConnectorPopup((_, ok) => {
    if (ok) setConnected(true);
  });

  return (
    <div className="mt-3 max-w-md rounded-xl border border-border bg-surface-2 dark:bg-card px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 shrink-0 rounded-lg bg-white border border-border flex items-center justify-center overflow-hidden">
          {info.logo && !logoFailed ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={info.logo} alt={`${info.service_title} logo`} className="w-6 h-6 object-contain" onError={() => setLogoFailed(true)} />
          ) : (
            <span className="text-xs font-semibold text-neutral-700">{info.service_title.charAt(0).toUpperCase()}</span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-foreground">{info.service_title}</div>
          <div className="text-xs text-muted-foreground">
            {connected
              ? "Connected — send your request again to use it."
              : `Connect ${info.service_title} so the assistant can act for you.`}
          </div>
        </div>
        {connected ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-500">
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 6L9 17l-5-5" />
            </svg>
            Connected
          </span>
        ) : (
          <button
            onClick={() => connect(info.service)}
            disabled={!!connecting}
            className="px-3 py-1.5 rounded-lg bg-brand text-brand-foreground text-xs font-medium hover:bg-brand-hover disabled:opacity-50 transition-colors"
          >
            {connecting ? "Connecting…" : "Connect"}
          </button>
        )}
      </div>
      {info.actions_added.length > 0 && (
        <div className="mt-2 text-[11px] text-muted-foreground">
          Enabled actions: {info.actions_added.join(", ")}
        </div>
      )}
      {error && <div className="mt-2 text-[11px] text-red-500">{error}</div>}
    </div>
  );
}
