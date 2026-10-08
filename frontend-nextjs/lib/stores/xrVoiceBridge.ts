import { create } from "zustand";

export type AgentUiState =
  | "disconnected"
  | "connecting"
  | "initializing"
  | "listening"
  | "thinking"
  | "speaking"
  | "unknown";

interface VoiceControls {
  setMicEnabled: (enabled: boolean) => Promise<void>;
  /** Ask the agent to stop talking immediately (RPC `agent.interrupt`). */
  interrupt: () => Promise<void>;
  /** Rate the agent's last answer; "down" also asks it to try again (RPC `agent.feedback`). */
  feedback: (rating: "up" | "down") => Promise<void>;
}

interface XRVoiceBridge {
  agentState: AgentUiState;
  micEnabled: boolean;
  /** Present only while a LiveKit room is mounted. */
  controls: VoiceControls | null;
  set: (partial: Partial<Omit<XRVoiceBridge, "set">>) => void;
}

/**
 * Bridges the LiveKit room (DOM, React context) to the WebXR scene. The room
 * publishes agent state + control functions here; the 3D scene and gesture
 * controller read them without needing LiveKit's React context.
 */
export const useXRVoiceBridge = create<XRVoiceBridge>((set) => ({
  agentState: "disconnected",
  micEnabled: true,
  controls: null,
  set: (partial) => set(partial),
}));
