import { create } from "zustand";
import { fetchWithRefresh } from "@/lib/api/client";

export interface ConnectionDetails {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
}

type VoiceState = "idle" | "fetching-token" | "connected" | "error";

/** "voice" = document Q&A call (mic button); "concierge" = avatar video call (Agent chat). */
export type AgentMode = "voice" | "concierge";

interface StartArgs {
  document_ids: string[];
  file_names: string[];
  mode?: AgentMode;
}

interface VoiceStore {
  state: VoiceState;
  mode: AgentMode;
  details: ConnectionDetails | null;
  error: string | null;
  start: (args: StartArgs) => Promise<void>;
  stop: () => void;
  setConnected: () => void;
  setError: (message: string) => void;
}

export const useVoiceStore = create<VoiceStore>((set, get) => ({
  state: "idle",
  mode: "voice",
  details: null,
  error: null,

  start: async ({ document_ids, file_names, mode = "voice" }) => {
    if (get().state !== "idle") return;
    set({ state: "fetching-token", mode, error: null });

    try {
      const res = await fetchWithRefresh("/api/livekit/token", {
        method: "POST",
        body: JSON.stringify({ document_ids, file_names, mode }),
      });

      if (!res.ok) {
        const msg = await res.text().catch(() => "");
        throw new Error(msg || `Token request failed (${res.status})`);
      }

      const details = (await res.json()) as ConnectionDetails;
      set({ details, state: "connected" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to start voice session";
      set({ state: "error", error: message, details: null });
    }
  },

  stop: () => {
    set({ state: "idle", details: null, error: null });
  },

  setConnected: () => set({ state: "connected" }),

  setError: (message) => set({ state: "error", error: message, details: null }),
}));
