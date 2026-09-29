"use client";

/**
 * Connect a Composio app via a popup — shared by the Connectors modal and the
 * chat "Connect <app>" card.
 *
 * Opens Composio's hosted OAuth page in a popup. /oauth-callback (loaded in the
 * popup) confirms with the backend and posts `connector-oauth-result`; we also
 * poll the connectors list as a fallback (blocked postMessage, popup closed
 * manually). `onDone(connected)` fires once either way.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { connectorsApi } from "@/lib/api/connectors";

export function useConnectorPopup(onDone?: (service: string, connected: boolean) => void) {
  const [connecting, setConnecting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => () => cleanupRef.current?.(), []);

  const connect = useCallback(async (service: string) => {
    setConnecting(service);
    setError(null);
    try {
      const callbackUrl = `${window.location.origin}/oauth-callback?connector=${encodeURIComponent(service)}`;
      const { auth_url } = await connectorsApi.connect(service, callbackUrl);
      const popup = window.open(auth_url, "connector-oauth", "width=600,height=760");
      if (!popup) {
        // Popup blocked → full-page redirect; /oauth-callback bounces back.
        window.location.href = auth_url;
        return;
      }

      let finished = false;
      const finish = async (connected?: boolean) => {
        if (finished) return;
        finished = true;
        cleanup();
        try {
          popup.close();
        } catch {
          /* ignore */
        }
        if (connected === undefined) {
          const res = await connectorsApi.list().catch(() => null);
          connected = !!res?.connectors.find((x) => x.service === service)?.connected;
        }
        setConnecting(null);
        onDoneRef.current?.(service, connected);
      };
      const onMessage = (e: MessageEvent) => {
        if (e.origin !== window.location.origin) return;
        if (e.data?.type !== "connector-oauth-result" || e.data?.connector !== service) return;
        finish(!!e.data.connected);
      };
      const poll = setInterval(async () => {
        if (popup.closed) return finish();
        const res = await connectorsApi.list().catch(() => null);
        if (res?.connectors.find((x) => x.service === service)?.connected) finish(true);
      }, 2500);
      const cleanup = () => {
        window.removeEventListener("message", onMessage);
        clearInterval(poll);
        cleanupRef.current = null;
      };
      window.addEventListener("message", onMessage);
      cleanupRef.current = cleanup;
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Connect failed");
      setConnecting(null);
    }
  }, []);

  return { connect, connecting, error };
}
