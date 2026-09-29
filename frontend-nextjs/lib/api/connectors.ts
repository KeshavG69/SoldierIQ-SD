/**
 * App connectors API client (Composio-backed on the server).
 *
 * Talks to the FastAPI router at /api/connectors/*. Connected apps expose
 * actions (GMAIL_SEND_EMAIL, …) that each user switches on/off; the chat agent
 * only gets the enabled actions of enabled, connected apps.
 *
 * Connect flow: POST /connect returns a Composio-hosted auth_url, which we open
 * in a popup. The popup lands on /oauth-callback?connector=<service>, which
 * confirms with POST /callback and messages this window.
 */
import apiClient from "./client";

export interface ConnectorAction {
  id: string;
  code: string;
  title: string;
  description: string | null;
  type: "read" | "write";
  enabled: boolean;
}

export interface Connector {
  id: string;
  service: string;
  name: string;
  category: string | null;
  description: string | null;
  /** Path under frontend /public (e.g. /connectors/gmail.svg). */
  logo: string | null;
  /** The user's on/off switch for the whole app. */
  enabled: boolean;
  status: string | null;
  connected: boolean;
  actions: ConnectorAction[];
}

export interface ConnectorsResponse {
  connectors: Connector[];
  total_enabled: number;
  limit: number;
}

export const connectorsApi = {
  list: async (): Promise<ConnectorsResponse> => {
    const res = await apiClient.get<ConnectorsResponse>("/connectors");
    return res.data;
  },

  /** Start the hosted Composio OAuth flow; returns the URL to open. */
  connect: async (
    service: string,
    callbackUrl: string
  ): Promise<{ service: string; auth_url: string; connected_account_id: string }> => {
    const res = await apiClient.post("/connectors/connect", {
      service,
      callback_url: callbackUrl,
    });
    return res.data;
  },

  /** Called by /oauth-callback once Composio redirects back. */
  confirm: async (
    connectedAccountId: string
  ): Promise<{ service: string; status: string | null; connected: boolean }> => {
    const res = await apiClient.post("/connectors/callback", {
      connected_account_id: connectedAccountId,
    });
    return res.data;
  },

  disconnect: async (service: string): Promise<void> => {
    await apiClient.post("/connectors/disconnect", { service });
  },

  toggleTool: async (toolId: string, enabled: boolean): Promise<void> => {
    await apiClient.post("/connectors/toggle", { tool_id: toolId, enabled });
  },

  toggleAction: async (actionId: string, enabled: boolean): Promise<void> => {
    await apiClient.post("/connectors/toggle", { action_id: actionId, enabled });
  },
};
