"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { formatDuration, videoOverviewApi, VideoStage } from "@/lib/api/videoOverview";

interface VideoOverviewViewerProps {
  workflowId: string;
  onClose: () => void;
  /** Called with the new workflow id after "Regenerate" starts a fresh generation */
  onSwitch: (workflowId: string) => void;
}

const STAGES: { key: VideoStage; label: string }[] = [
  { key: "reading", label: "Reading your documents" },
  { key: "scripting", label: "Writing the script" },
  { key: "illustrating", label: "Illustrating the scenes" },
  { key: "narrating", label: "Recording the narration" },
  { key: "composing", label: "Editing the video" },
];

export default function VideoOverviewViewer({ workflowId, onClose, onSwitch }: VideoOverviewViewerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [showTranscript, setShowTranscript] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["videoOverview", workflowId],
    queryFn: () => videoOverviewApi.getById(workflowId),
    // Poll until the background generation finishes
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 4000 : false),
    // Presigned media links must not change under a playing video
    refetchOnWindowFocus: false,
  });

  const regenerate = useMutation({
    mutationFn: () => videoOverviewApi.regenerate(workflowId),
    onSuccess: ({ workflow_id }) => {
      queryClient.invalidateQueries({ queryKey: ["videoOverviews"] });
      onSwitch(workflow_id);
    },
  });

  // Captions are served inline (a same-origin blob URL) so no storage CORS setup is needed
  const captionsUrl = useMemo(
    () => (data?.captions_vtt ? URL.createObjectURL(new Blob([data.captions_vtt], { type: "text/vtt" })) : null),
    [data?.captions_vtt]
  );
  useEffect(() => {
    return () => {
      if (captionsUrl) URL.revokeObjectURL(captionsUrl);
    };
  }, [captionsUrl]);

  const status = data?.status;
  const chapters = data?.chapters ?? [];
  const isProcessing = isLoading || status === "processing";
  const stageIndex = STAGES.findIndex((s) => s.key === data?.stage);
  const activeChapter = chapters.reduce((active, c, i) => (currentTime >= c.start ? i : active), 0);

  const seek = (seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = seconds;
    video.play().catch(() => {});
  };

  return (
    <Dialog open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-5xl p-0 gap-0 flex flex-col max-h-[92vh] overflow-hidden">
        {/* Header */}
        <div className="border-b border-border px-5 py-4 pr-12">
          <DialogTitle className="text-base font-semibold text-foreground truncate">
            {status === "completed" ? data?.title : "Video overview"}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground mt-0.5">
            {data ? (
              <>
                {status === "completed" && data.duration_s ? `${formatDuration(data.duration_s)} · ` : ""}
                Based on {data.document_count} {data.document_count === 1 ? "source" : "sources"}
                {data.settings?.format && <span className="capitalize"> · {data.settings.format}</span>}
                {data.settings?.style && <span className="capitalize"> · {data.settings.style.replace("_", " ")}</span>}
              </>
            ) : (
              "Loading…"
            )}
          </DialogDescription>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto tactical-scrollbar bg-muted/40">
          {isError ? (
            <div className="px-5 py-16 text-center text-sm text-muted-foreground">Couldn&apos;t load this video.</div>
          ) : isProcessing ? (
            <div className="px-5 py-14 flex flex-col items-center">
              <div className="w-8 h-8 border-2 border-border border-t-brand rounded-full animate-spin mb-5" />
              <ol className="flex flex-col gap-2 mb-5">
                {STAGES.map((stage, i) => {
                  const done = stageIndex > i;
                  const active = stageIndex === i || (stageIndex === -1 && i === 0);
                  return (
                    <li key={stage.key} className="flex items-center gap-2 text-sm">
                      <span
                        className={`w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-bold ${
                          done
                            ? "bg-emerald-500 text-white"
                            : active
                              ? "bg-brand text-brand-foreground"
                              : "bg-secondary text-muted-foreground"
                        }`}
                      >
                        {done ? "✓" : i + 1}
                      </span>
                      <span className={active ? "text-foreground font-medium" : "text-muted-foreground"}>
                        {stage.label}
                      </span>
                    </li>
                  );
                })}
              </ol>
              <p className="text-xs text-muted-foreground max-w-sm text-center">
                This usually takes 2–5 minutes. You can close this; it keeps going and appears under Recent videos.
              </p>
            </div>
          ) : status === "failed" ? (
            <div className="px-5 py-16 flex flex-col items-center text-center">
              <p className="text-sm font-medium text-foreground">Generation failed</p>
              {data?.error && <p className="text-xs text-muted-foreground mt-1 max-w-md">{data.error}</p>}
              <Button className="mt-4" onClick={() => regenerate.mutate()} disabled={regenerate.isPending}>
                Try again
              </Button>
            </div>
          ) : data?.video_url ? (
            <div className="p-4 flex flex-col gap-3">
              <video
                ref={videoRef}
                src={data.video_url}
                poster={data.poster_url ?? undefined}
                controls
                playsInline
                preload="metadata"
                onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
                className="w-full aspect-video rounded-md bg-black"
              >
                {captionsUrl && <track kind="captions" src={captionsUrl} srcLang="en" label="English" default />}
              </video>

              {/* Chapters */}
              {chapters.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground mb-2">Chapters</h3>
                  <div className="flex gap-2 overflow-x-auto tactical-scrollbar pb-1">
                    {chapters.map((chapter, i) => (
                      <button
                        key={`${chapter.start}-${i}`}
                        type="button"
                        onClick={() => seek(chapter.start)}
                        className={`shrink-0 w-36 rounded-md overflow-hidden border-2 text-left transition-colors ${
                          i === activeChapter ? "border-brand" : "border-transparent hover:border-border"
                        }`}
                      >
                        {chapter.thumb_url && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={chapter.thumb_url} alt="" className="w-full aspect-video object-cover bg-card" />
                        )}
                        <div className="px-1.5 py-1 bg-card">
                          <div className="text-[11px] text-muted-foreground">{formatDuration(chapter.start)}</div>
                          <div className="text-xs text-foreground truncate">{chapter.title}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Transcript */}
              {data.transcript?.length > 0 && (
                <div>
                  <button
                    type="button"
                    onClick={() => setShowTranscript((s) => !s)}
                    className="text-xs text-brand hover:underline"
                  >
                    {showTranscript ? "Hide transcript" : "Show transcript"}
                  </button>
                  {showTranscript && (
                    <div className="mt-1.5 rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground flex flex-col gap-2">
                      {data.transcript.map((paragraph, i) => (
                        <p key={i}>
                          {chapters[i] && (
                            <button
                              type="button"
                              onClick={() => seek(chapters[i].start)}
                              className="mr-1.5 text-xs text-brand hover:underline"
                            >
                              {formatDuration(chapters[i].start)}
                            </button>
                          )}
                          {paragraph}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : null}
        </div>

        {/* Footer */}
        {status === "completed" && (
          <div className="border-t border-border px-5 py-3 flex items-center justify-between gap-3">
            <p className="text-[11px] text-muted-foreground truncate" title={data?.sources.join(", ")}>
              {data?.sources.length ? `Sources: ${data.sources.join(", ")}` : ""}
            </p>
            <div className="flex shrink-0 gap-2">
              <Button variant="outline" onClick={() => regenerate.mutate()} disabled={regenerate.isPending}>
                {regenerate.isPending ? "Starting…" : "Regenerate"}
              </Button>
              {data?.download_url && (
                <a
                  href={data.download_url}
                  className="inline-flex h-8 items-center rounded-lg bg-primary px-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/80 transition-colors"
                >
                  Download MP4
                </a>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
