"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Busy, Button, C, SCREEN_H, SCREEN_W, ScreenHeader, T, useScreenHandlers } from "../ui";
import { podcastApi } from "@/lib/api/podcast";
import { formatDuration } from "@/lib/api/videoOverview";
import { useDocumentStore } from "@/lib/stores/documentStore";
import { useXRUi } from "@/lib/stores/xrUiStore";

// No list endpoint exists for podcasts, so remember the last episode on this device.
const LAST_EPISODE_KEY = "soldieriq.xr.lastPodcast";
const readLast = () => {
  try {
    return localStorage.getItem(LAST_EPISODE_KEY);
  } catch {
    return null;
  }
};
const writeLast = (id: string) => {
  try {
    localStorage.setItem(LAST_EPISODE_KEY, id);
  } catch {
    /* storage unavailable */
  }
};

export default function AudioScreen() {
  const [episodeId, setEpisodeId] = useState<string | null>(null);
  if (episodeId) return <Episode id={episodeId} onExit={() => setEpisodeId(null)} />;
  return <Start onStarted={setEpisodeId} />;
}

function Start({ onStarted }: { onStarted: (id: string) => void }) {
  const selectedDocs = useDocumentStore((s) => s.selectedDocs);
  const setScreen = useXRUi((s) => s.setScreen);
  const last = useMemo(readLast, []);

  const generate = useMutation({
    mutationFn: () => podcastApi.generatePodcast(Array.from(selectedDocs)),
    onSuccess: ({ episode_id }) => {
      writeLast(episode_id);
      onStarted(episode_id);
    },
  });
  const start = () => {
    if (selectedDocs.size === 0 || generate.isPending) return false;
    generate.mutate();
    return true;
  };

  useScreenHandlers({ confirm: start });

  return (
    <group>
      <ScreenHeader title="Audio overview" subtitle="A podcast-style discussion of your selected documents" />
      <T position={[0, 0.1, 0]} fontSize={0.022} color={C.muted} maxWidth={SCREEN_W - 0.2} textAlign="center">
        {selectedDocs.size > 0
          ? `Generate an episode from ${selectedDocs.size} selected document${selectedDocs.size === 1 ? "" : "s"}.`
          : "Select documents first."}
      </T>
      {generate.isError && (
        <T position={[0, 0.04, 0]} fontSize={0.016} color={C.danger}>
          Could not start audio generation.
        </T>
      )}
      <Button
        label={generate.isPending ? "Starting…" : selectedDocs.size > 0 ? "Generate episode" : "Select documents"}
        width={0.3}
        color={C.accent}
        disabled={generate.isPending}
        position={[0, -0.04, 0]}
        onClick={() => (selectedDocs.size > 0 ? start() : setScreen("documents"))}
      />
      {last && <Button label="Play last episode" width={0.3} position={[0, -0.12, 0]} onClick={() => onStarted(last)} />}
    </group>
  );
}

function Episode({ id, onExit }: { id: string; onExit: () => void }) {
  const { data, isError } = useQuery({
    queryKey: ["podcast", id],
    queryFn: () => podcastApi.getPodcastStatus(id),
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "completed" || s === "failed" ? false : 5000;
    },
  });
  const audioKey = data?.status === "completed" ? data.audio_file_key : undefined;
  const { data: audioUrl } = useQuery({
    queryKey: ["podcastAudio", audioKey],
    enabled: !!audioKey,
    staleTime: 30 * 60 * 1000,
    queryFn: async () => {
      const res = await fetch(`/api/files/presigned-url?file_key=${encodeURIComponent(audioKey!)}`);
      const body = (await res.json()) as { url?: string };
      if (!body.url) throw new Error("No audio URL");
      return body.url;
    },
  });

  const title = data?.title || "Audio overview";
  const failed = isError || data?.status === "failed";
  return (
    <group>
      <ScreenHeader title={title} subtitle={audioUrl ? "Thumbs up to play/pause · swipe to skip 15s" : undefined} onBack={onExit} backLabel="New episode" />
      {audioUrl ? (
        <AudioPlayer url={audioUrl} summary={data?.summary} onExit={onExit} />
      ) : failed ? (
        <Message text={data?.error_message || "Audio generation failed."} color={C.danger} onExit={onExit} />
      ) : (
        <Message
          text={data?.status === "script_generated" ? "Recording the conversation…" : "Writing the script… episodes take a few minutes."}
          busy
          onExit={onExit}
        />
      )}
    </group>
  );
}

function Message({ text, color, busy, onExit }: { text: string; color?: string; busy?: boolean; onExit: () => void }) {
  useScreenHandlers({ back: () => (onExit(), true) });
  return busy ? (
    <Busy text={text} />
  ) : (
    <T fontSize={0.02} color={color} maxWidth={SCREEN_W - 0.1}>
      {text}
    </T>
  );
}

function AudioPlayer({ url, summary, onExit }: { url: string; summary?: string; onExit: () => void }) {
  const audio = useMemo(() => new Audio(url), [url]);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    const onTime = () => setTime(audio.currentTime);
    const onMeta = () => setDuration(audio.duration || 0);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("loadedmetadata", onMeta);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("loadedmetadata", onMeta);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    };
  }, [audio]);

  const toggle = () => {
    if (audio.paused) void audio.play();
    else audio.pause();
    return true;
  };
  const skip = (s: number) => () => {
    audio.currentTime = Math.max(0, Math.min(duration || 0, audio.currentTime + s));
    return true;
  };

  useScreenHandlers({ confirm: toggle, next: skip(15), prev: skip(-15), back: () => (onExit(), true) });

  const w = SCREEN_W - 0.1;
  const progress = duration ? time / duration : 0;
  return (
    <group>
      <T position={[-SCREEN_W / 2 + 0.05, 0.17, 0]} anchorX="left" anchorY="top" fontSize={0.017} color={C.muted} maxWidth={w}>
        {summary ? summary.slice(0, 600) : "Your audio overview is ready."}
      </T>
      <mesh position={[0, -0.14, 0]}>
        <planeGeometry args={[w, 0.01]} />
        <meshBasicMaterial color={C.border} />
      </mesh>
      <mesh position={[-w / 2 + (w * progress) / 2, -0.14, 0.001]}>
        <planeGeometry args={[Math.max(0.0001, w * progress), 0.01]} />
        <meshBasicMaterial color={C.accent} />
      </mesh>
      <T position={[0, -0.17, 0]} fontSize={0.015} color={C.muted}>
        {`${formatDuration(time)} / ${formatDuration(duration)}`}
      </T>
      <group position={[0, -SCREEN_H / 2 + 0.06, 0]}>
        <Button label="-15s" width={0.1} position={[-0.15, 0, 0]} onClick={skip(-15)} />
        <Button label={playing ? "Pause" : "Play"} width={0.14} color={C.accent} position={[0, 0, 0]} onClick={toggle} />
        <Button label="+15s" width={0.1} position={[0.15, 0, 0]} onClick={skip(15)} />
      </group>
    </group>
  );
}
