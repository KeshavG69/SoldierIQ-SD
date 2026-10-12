"use client";

import { useEffect } from "react";
import {
  BarVisualizer,
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  VideoTrack,
  useVoiceAssistant,
} from "@livekit/components-react";
import "@livekit/components-styles";
import { Track } from "livekit-client";
import { X } from "lucide-react";

import { useVoiceStore } from "@/lib/stores/voiceStore";

/**
 * Full-screen call UX — mounted once at the dashboard root. When the voice store
 * has `connectionDetails`, renders a `<LiveKitRoom>` covering the viewport: a bar
 * visualizer for the document voice call, or the avatar's video for the concierge.
 */
export default function VoiceSession() {
  const { state, mode, details, error, stop } = useVoiceStore();
  const active = state === "connected" && details !== null;

  // Auto-clear after a brief error flash so the UI doesn't stay stuck.
  useEffect(() => {
    if (state !== "error") return;
    const t = setTimeout(() => stop(), 4000);
    return () => clearTimeout(t);
  }, [state, stop]);

  if (!active) {
    if (state === "error" && error) {
      return (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 rounded-lg bg-red-600 px-4 py-2 text-sm text-white shadow-lg">
          {error}
        </div>
      );
    }
    if (state === "fetching-token") {
      return (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 rounded-lg bg-card px-4 py-2 text-sm text-white shadow-lg">
          Connecting…
        </div>
      );
    }
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/95 backdrop-blur-sm">
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
        className="h-full w-full"
      >
        {mode === "concierge" ? <AvatarRoomContent /> : <VoiceRoomContent />}
        <RoomAudioRenderer />
      </LiveKitRoom>
    </div>
  );
}

function VoiceRoomContent() {
  const { state: agentState, audioTrack } = useVoiceAssistant();
  const stop = useVoiceStore((s) => s.stop);

  const label = agentStateLabel(agentState);

  return (
    <div className="relative flex h-full w-full flex-col items-center justify-center">
      {/* End call — top-right */}
      <button
        type="button"
        onClick={stop}
        aria-label="End call"
        className="absolute right-6 top-6 flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-sm font-medium text-white hover:bg-white/20 transition-colors"
      >
        <X className="h-4 w-4" />
        End
      </button>

      {/* Visualizer */}
      <div className="flex h-56 w-full max-w-lg items-center justify-center">
        <BarVisualizer
          state={agentState}
          barCount={7}
          trackRef={audioTrack}
          className="h-full w-full [&>.lk-audio-bar]:bg-white"
        />
      </div>

      {/* State label */}
      <div className="mt-10 text-center">
        <div className="text-xs uppercase tracking-[0.2em] text-white/50">
          {label.eyebrow}
        </div>
        <div className="mt-2 text-lg font-medium text-white">{label.main}</div>
      </div>
    </div>
  );
}

/** Concierge call: the avatar worker publishes the agent's video (and lip-synced audio). */
function AvatarRoomContent() {
  const { state: agentState, videoTrack, audioTrack } = useVoiceAssistant();
  const stop = useVoiceStore((s) => s.stop);

  const label = agentStateLabel(agentState, "Agent chat");
  // The agent only goes live after its avatar joins; live with no video means the
  // avatar couldn't start and the agent fell back to voice-only.
  const voiceOnly =
    !videoTrack && (agentState === "listening" || agentState === "thinking" || agentState === "speaking");

  return (
    <div className="relative flex h-full w-full flex-col items-center justify-center px-4">
      <button
        type="button"
        onClick={stop}
        aria-label="End call"
        className="absolute right-6 top-6 flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-sm font-medium text-white hover:bg-white/20 transition-colors"
      >
        <X className="h-4 w-4" />
        End
      </button>

      {/* Sized by the avatar's own video: Tavus is landscape, Simli square, LemonSlice portrait */}
      <div className="relative max-w-full overflow-hidden rounded-2xl bg-white/5 ring-1 ring-white/10">
        {videoTrack ? (
          <VideoTrack
            trackRef={videoTrack}
            className="block h-auto w-auto max-h-[min(65vh,600px)] max-w-[min(90vw,960px)]"
          />
        ) : voiceOnly ? (
          <div className="flex aspect-square h-[min(65vh,600px)] max-w-full flex-col items-center justify-center gap-4 px-6">
            <BarVisualizer
              state={agentState}
              barCount={5}
              trackRef={audioTrack}
              className="h-32 w-full [&>.lk-audio-bar]:bg-white"
            />
            <span className="text-center text-xs text-white/50">Video unavailable — voice only</span>
          </div>
        ) : (
          <div className="flex aspect-square h-[min(65vh,600px)] max-w-full flex-col items-center justify-center gap-3 text-white/60">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white/70" />
            <span className="text-sm">Bringing the concierge online…</span>
          </div>
        )}
      </div>

      <div className="mt-8 flex items-center gap-6">
        <div className="text-center">
          <div className="text-xs uppercase tracking-[0.2em] text-white/50">{label.eyebrow}</div>
          <div className="mt-1 text-lg font-medium text-white">{label.main}</div>
        </div>
        <TrackToggle
          source={Track.Source.Microphone}
          className="flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors [&>svg]:h-5 [&>svg]:w-5"
        />
      </div>
    </div>
  );
}

function agentStateLabel(
  state: ReturnType<typeof useVoiceAssistant>["state"],
  eyebrow = "Voice call",
) {
  switch (state) {
    case "connecting":
      return { eyebrow, main: "Connecting…" };
    case "initializing":
      return { eyebrow, main: "Starting up…" };
    case "listening":
      return { eyebrow, main: "Listening" };
    case "thinking":
      return { eyebrow, main: "Thinking…" };
    case "speaking":
      return { eyebrow, main: "Speaking" };
    case "disconnected":
      return { eyebrow, main: "Disconnected" };
    default:
      return { eyebrow, main: "Ready" };
  }
}
