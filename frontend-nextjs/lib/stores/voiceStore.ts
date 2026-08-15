import { create } from "zustand";
import { fetchWithRefresh } from "@/lib/api/client";

export interface ConnectionDetails {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
}

type VoiceState = "idle" | "fetching-token" | "connected" | "error";

interface StartArgs {
  document_ids: string[];
  file_names: string[];
}

interface VoiceStore {
  state: VoiceState;
  details: ConnectionDetails | null;
  error: string | null;
  start: (args: StartArgs) => Promise<void>;
  stop: () => void;
  setConnected: () => void;
  setError: (message: string) => void;
}

export const useVoiceStore = create<VoiceStore>((set, get) => ({
  state: "idle",
  details: null,
  error: null,

  start: async ({ document_ids, file_names }) => {
    if (get().state !== "idle") return;
    set({ state: "fetching-token", error: null });

    try {
      const res = await fetchWithRefresh("/api/livekit/token", {
        method: "POST",
        body: JSON.stringify({ document_ids, file_names }),
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
