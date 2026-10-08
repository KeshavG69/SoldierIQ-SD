"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SRGBColorSpace, VideoTexture } from "three";

import { Busy, Button, C, SCREEN_H, SCREEN_W, SavedList, ScreenHeader, T, fmtDate, mediaUrl, useScreenHandlers } from "../ui";
import { formatDuration, videoOverviewApi, type VideoChapter, type VideoStage } from "@/lib/api/videoOverview";
import { useDocumentStore } from "@/lib/stores/documentStore";

const STAGE_TEXT: Partial<Record<VideoStage, string>> = {
  queued: "Queued…",
  reading: "Reading your documents…",
  scripting: "Writing the script…",
  illustrating: "Illustrating scenes…",
  narrating: "Recording narration…",
  composing: "Composing the video…",
};

export default function VideoScreen() {
  const [viewId, setViewId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedDocs = useDocumentStore((s) => s.selectedDocs);
  const queryClient = useQueryClient();

  const list = useQuery({ queryKey: ["videoOverviews"], queryFn: videoOverviewApi.list, enabled: !viewId });
  const generate = useMutation({
    mutationFn: () =>
      videoOverviewApi.generate(Array.from(selectedDocs), { format: "explainer", style: "classic", voice: "sarah" }),
    onSuccess: ({ workflow_id }) => {
      queryClient.invalidateQueries({ queryKey: ["videoOverviews"] });
      setViewId(workflow_id);
    },
    onError: () => setError("Could not start video generation."),
  });

  if (viewId) return <VideoViewer id={viewId} onExit={() => setViewId(null)} />;

  return (
    <group>
      <ScreenHeader title="Video overview" subtitle="Open a video or generate an explainer from your selected documents" />
      <SavedList
        items={(list.data ?? []).map((v) => ({
          id: v.workflow_id,
          title: v.title ?? "Untitled video",
          subtitle:
            v.status === "completed"
              ? `${formatDuration(v.duration_s)} · ${fmtDate(v.created_at)}`
              : v.status === "processing"
                ? "generating…"
                : "failed",
          disabled: v.status === "failed",
        }))}
        loading={list.isLoading}
        onOpen={setViewId}
        onGenerate={() => {
          setError(null);
          generate.mutate();
        }}
        generating={generate.isPending}
        generateLabel="Generate video"
        canGenerate={selectedDocs.size > 0}
        emptyText="No video overviews yet."
        error={error}
      />
    </group>
  );
}

function VideoViewer({ id, onExit }: { id: string; onExit: () => void }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["videoOverview", id],
    queryFn: () => videoOverviewApi.getById(id),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 5000 : false),
  });

  const title = data?.title ?? "Video overview";
  const ready = data?.status === "completed" && !!data.video_url;

  return (
    <group>
      <ScreenHeader title={title} subtitle={ready ? "Swipe for chapters · thumbs up to play/pause" : undefined} onBack={onExit} backLabel="All videos" />
      {ready ? (
        <Player url={data.video_url!} chapters={data.chapters ?? []} onExit={onExit} />
      ) : isLoading || data?.status === "processing" ? (
        <BusyWithBack text={(data?.stage && STAGE_TEXT[data.stage]) || "Starting…"} onExit={onExit} />
      ) : (
        <ErrorWithBack text={isError ? "This video could not be loaded." : data?.error || "Video generation failed."} onExit={onExit} />
      )}
    </group>
  );
}

function BusyWithBack({ text, onExit }: { text: string; onExit: () => void }) {
  useScreenHandlers({ back: () => (onExit(), true) });
  return <Busy text={`${text} Videos take several minutes.`} />;
}

function ErrorWithBack({ text, onExit }: { text: string; onExit: () => void }) {
  useScreenHandlers({ back: () => (onExit(), true) });
  return (
    <T fontSize={0.02} color={C.danger} maxWidth={SCREEN_W - 0.1}>
      {text}
    </T>
  );
}

function Player({ url, chapters, onExit }: { url: string; chapters: VideoChapter[]; onExit: () => void }) {
  const video = useMemo(() => {
    const v = document.createElement("video");
    v.crossOrigin = "anonymous";
    v.playsInline = true;
    v.preload = "auto";
    v.src = mediaUrl(url);
    return v;
  }, [url]);
  const texture = useMemo(() => {
    const t = new VideoTexture(video);
    t.colorSpace = SRGBColorSpace;
    return t;
  }, [video]);

  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const onTime = () => setTime(video.currentTime);
    const onMeta = () => setDuration(video.duration || 0);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onError = () => setFailed(true);
    video.addEventListener("timeupdate", onTime);
    video.addEventListener("loadedmetadata", onMeta);
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    video.addEventListener("error", onError);
    return () => {
      video.removeEventListener("timeupdate", onTime);
      video.removeEventListener("loadedmetadata", onMeta);
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
      video.removeEventListener("error", onError);
      video.pause();
      video.removeAttribute("src");
      video.load();
      texture.dispose();
    };
  }, [video, texture]);

  const toggle = () => {
    if (video.paused) void video.play().catch(() => setFailed(true));
    else video.pause();
    return true;
  };
  const seek = (t: number) => {
    video.currentTime = Math.max(0, Math.min(duration || t, t));
    return true;
  };
  const chapterIndex = chapters.reduce((acc, c, i) => (time + 0.5 >= c.start ? i : acc), 0);
  const nextChapter = () => (chapterIndex + 1 < chapters.length ? seek(chapters[chapterIndex + 1].start) : false);
  const prevChapter = () => {
    // Within the first few seconds of a chapter, go to the previous one; otherwise restart this one.
    const start = chapters[chapterIndex]?.start ?? 0;
    if (time - start > 3 || chapterIndex === 0) return seek(start);
    return seek(chapters[chapterIndex - 1].start);
  };

  useScreenHandlers({
    next: chapters.length ? nextChapter : () => seek(time + 10),
    prev: chapters.length ? prevChapter : () => seek(time - 10),
    confirm: toggle,
    back: () => (onExit(), true),
  });

  const w = SCREEN_W - 0.06;
  const h = Math.min(0.4, w * (9 / 16));
  const progress = duration ? time / duration : 0;
  const videoY = 0.0;
  const barY = videoY - h / 2 - 0.025;
  return (
    <group>
      <mesh position={[0, videoY, 0.002]} onClick={(e) => (e.stopPropagation(), toggle())}>
        <planeGeometry args={[(h * 16) / 9, h]} />
        <meshBasicMaterial map={texture} toneMapped={false} />
      </mesh>
      {!playing && (
        <T position={[0, videoY, 0.01]} fontSize={0.03}>
          {failed ? "Playback failed" : time > 0 ? "Paused" : "Pinch to play"}
        </T>
      )}
      <mesh position={[0, barY, 0.003]}>
        <planeGeometry args={[w, 0.008]} />
        <meshBasicMaterial color={C.border} />
      </mesh>
      <mesh position={[-w / 2 + (w * progress) / 2, barY, 0.004]}>
        <planeGeometry args={[Math.max(0.0001, w * progress), 0.008]} />
        <meshBasicMaterial color={C.accent} />
      </mesh>
      <group position={[0, -SCREEN_H / 2 + 0.04, 0]}>
        <Button label="-10s" width={0.09} position={[-0.25, 0, 0]} onClick={() => seek(time - 10)} />
        <Button label={playing ? "Pause" : "Play"} width={0.12} color={C.accent} position={[-0.13, 0, 0]} onClick={toggle} />
        <Button label="+10s" width={0.09} position={[-0.01, 0, 0]} onClick={() => seek(time + 10)} />
        <T position={[0.26, 0, 0]} fontSize={0.015} color={C.muted} maxWidth={0.4}>
          {`${formatDuration(time)} / ${formatDuration(duration)}${chapters[chapterIndex] ? `  ·  ${chapters[chapterIndex].title}` : ""}`}
        </T>
      </group>
    </group>
  );
}
