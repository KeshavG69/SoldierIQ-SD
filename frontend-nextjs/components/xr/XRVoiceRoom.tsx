"use client";

import { useEffect } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useLocalParticipant,
  useRoomContext,
  useVoiceAssistant,
} from "@livekit/components-react";

import { useVoiceStore } from "@/lib/stores/voiceStore";
import { useXRVoiceBridge, type AgentUiState } from "@/lib/stores/xrVoiceBridge";

/**
 * Headless LiveKit room for VR mode. Same voice agent session as the dashboard's
 * <VoiceSession />, but with no full-screen UI — the agent's state and controls
 * are pushed into `useXRVoiceBridge` for the 3D scene to render and drive.
 */
export default function XRVoiceRoom() {
  const { state, details, stop } = useVoiceStore();
  const active = state === "connected" && details !== null;

  useEffect(() => {
    if (state !== "error") return;
    const t = setTimeout(() => stop(), 4000);
    return () => clearTimeout(t);
  }, [state, stop]);

  if (!active) return null;

  return (
    <LiveKitRoom
      token={details.participantToken}
      serverUrl={details.serverUrl}
      connect={true}
      audio={true}
      video={false}
      onDisconnected={() => stop()}
      onError={(err) => {
        console.error("LiveKit error:", err);
        stop();
      }}
      style={{ display: "none" }}
    >
      <VoiceBridge />
      <RoomAudioRenderer />
    </LiveKitRoom>
  );
}

function VoiceBridge() {
  const room = useRoomContext();
  const { agent, state } = useVoiceAssistant();
  const { isMicrophoneEnabled } = useLocalParticipant();
  const set = useXRVoiceBridge((s) => s.set);

  useEffect(() => {
    set({ agentState: (state as AgentUiState) ?? "unknown" });
  }, [state, set]);

  useEffect(() => {
    set({ micEnabled: isMicrophoneEnabled });
  }, [isMicrophoneEnabled, set]);

  useEffect(() => {
    const callAgent = async (method: string, payload: string) => {
      if (!agent) return;
      try {
        await room.localParticipant.performRpc({ destinationIdentity: agent.identity, method, payload });
      } catch (err) {
        console.warn(`[xr] RPC ${method} failed:`, err);
      }
    };

    set({
      controls: {
        setMicEnabled: async (enabled) => {
          await room.localParticipant.setMicrophoneEnabled(enabled);
        },
        interrupt: () => callAgent("agent.interrupt", ""),
        feedback: (rating) => callAgent("agent.feedback", JSON.stringify({ rating })),
      },
    });
  }, [room, agent, set]);

  useEffect(
    () => () => set({ controls: null, agentState: "disconnected", micEnabled: true }),
    [set],
  );

  return null;
}
