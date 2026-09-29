"use client";

/**
 * OAuth callback landing page for Composio-managed connectors (SharePoint,
 * Google Drive, and the agent app connectors from ConnectorsModal).
 *
 * App connectors arrive with `?connector=<service>` (set by us) plus Composio's
 * `connected_account_id` / `connectedAccountId`; for those we confirm with the
 * backend (marks the connection ACTIVE in our DB) before messaging the opener.
 *
 * Composio runs the hosted OAuth flow in a popup and redirects here only AFTER
 * it finishes — so simply arriving here (without an `error` query param) means
 * the connection succeeded. No status polling needed. We then:
 *   - if opened as a popup, message the opener and close ourselves;
 *   - otherwise, bounce back to the dashboard.
 */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { connectorsApi } from "@/lib/api/connectors";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [msg, setMsg] = useState("Finishing the connection…");

  useEffect(() => {
    let cancelled = false;
    const connector = params.get("connector");
    const accountId = params.get("connected_account_id") || params.get("connectedAccountId");

    (async () => {
      let connected = !params.get("error");
      if (connector) {
        setMsg("Finishing the connection…");
        if (accountId) {
          try {
            connected = (await connectorsApi.confirm(accountId)).connected;
          } catch {
            connected = false;
          }
        }
      }
      if (cancelled) return;
      setMsg(connected ? "Connected!" : "Connection was not completed.");

      if (window.opener) {
        try {
          window.opener.postMessage(
            connector
              ? { type: "connector-oauth-result", connector, connected }
              : { type: "sharepoint-oauth-result", connected },
            window.location.origin
          );
        } catch {
          /* ignore */
        }
        window.close();
        // Some browsers block close() for non-script-opened windows.
        setMsg("You can close this window.");
        return;
      }

      // Full-page fallback (popup was blocked): bounce back to the dashboard.
      await sleep(800);
      if (!cancelled) router.replace("/dashboard");
    })();
    return () => {
      cancelled = true;
    };
  }, [router, params]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-background text-foreground">
      <div className="w-5 h-5 border-2 border-brand/30 border-t-amber-400 rounded-full animate-spin" />
      <div className="text-sm text-muted-foreground">{msg}</div>
    </div>
  );
}

export default function OAuthCallback() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center bg-background text-muted-foreground">Loading…</div>}>
      <CallbackInner />
    </Suspense>
  );
}
