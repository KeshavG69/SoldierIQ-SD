"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  formatDuration,
  videoOverviewApi,
  VideoFormat,
  VideoOptions,
  VideoStyle,
  VideoVoice,
} from "@/lib/api/videoOverview";
import Segmented from "./Segmented";

interface VideoOverviewSetupDialogProps {
  open: boolean;
  documentCount: number;
  onClose: () => void;
  onGenerate: (options: VideoOptions) => void;
  onOpenVideo: (workflowId: string) => void;
}

const FORMAT_OPTIONS: { value: VideoFormat; label: string; hint: string }[] = [
  { value: "explainer", label: "Explainer", hint: "~4 min" },
  { value: "brief", label: "Brief", hint: "~1.5 min" },
];

const STYLE_OPTIONS: { value: VideoStyle; label: string }[] = [
  { value: "classic", label: "Classic" },
  { value: "whiteboard", label: "Whiteboard" },
  { value: "watercolor", label: "Watercolor" },
  { value: "papercraft", label: "Papercraft" },
  { value: "retro_print", label: "Retro print" },
  { value: "tactical", label: "Tactical" },
];

const VOICE_OPTIONS: { value: VideoVoice; label: string }[] = [
  { value: "sarah", label: "Sarah" },
  { value: "brian", label: "Brian" },
  { value: "george", label: "George" },
];

function formatDate(iso: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function VideoOverviewSetupDialog({
  open,
  documentCount,
  onClose,
  onGenerate,
  onOpenVideo,
}: VideoOverviewSetupDialogProps) {
  const [format, setFormat] = useState<VideoFormat>("explainer");
  const [style, setStyle] = useState<VideoStyle>("classic");
  const [voice, setVoice] = useState<VideoVoice>("sarah");
  const [focus, setFocus] = useState("");

  const { data: saved, isLoading: isLoadingSaved } = useQuery({
    queryKey: ["videoOverviews"],
    queryFn: videoOverviewApi.list,
    enabled: open,
    // Keep refreshing while anything is still generating
    refetchInterval: (query) =>
      open && query.state.data?.some((v) => v.status === "processing") ? 4000 : false,
  });

  const handleGenerate = () => {
    onGenerate({ format, style, voice, focus: focus.trim() || undefined });
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Video overview</DialogTitle>
          <DialogDescription>
            {documentCount > 0
              ? `A narrated, illustrated video from ${documentCount} selected ${documentCount === 1 ? "source" : "sources"}.`
              : "Select documents to generate a new video, or open a saved one."}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-foreground">Format</label>
            <div className="grid grid-cols-2 gap-1 rounded-lg bg-secondary p-1">
              {FORMAT_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setFormat(option.value)}
                  aria-pressed={format === option.value}
                  className={`rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                    format === option.value
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {option.label}
                  <span className="ml-1 text-muted-foreground">({option.hint})</span>
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-foreground">Visual style</label>
            <div className="grid grid-cols-3 gap-1">
              {STYLE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setStyle(option.value)}
                  aria-pressed={style === option.value}
                  className={`rounded-md border px-2 py-1.5 text-xs font-medium transition-colors ${
                    style === option.value
                      ? "border-brand/60 bg-brand/10 text-foreground"
                      : "border-border text-muted-foreground hover:text-foreground hover:bg-secondary"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-foreground">Narrator</label>
            <Segmented options={VOICE_OPTIONS} value={voice} onChange={setVoice} />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="video-focus" className="text-xs font-medium text-foreground">
              What should it focus on? <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <textarea
              id="video-focus"
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              maxLength={500}
              rows={2}
              placeholder="e.g. Explain the recovery decision for new platoon leaders"
              className="w-full resize-none rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleGenerate} disabled={documentCount === 0}>
            Generate
          </Button>
        </DialogFooter>

        {/* Saved videos */}
        <div className="border-t border-border pt-3">
          <h3 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground mb-2">Recent videos</h3>
          {isLoadingSaved ? (
            <p className="text-xs text-muted-foreground">Loading…</p>
          ) : !saved || saved.length === 0 ? (
            <p className="text-xs text-muted-foreground">No video overviews yet.</p>
          ) : (
            <div className="flex max-h-56 flex-col gap-1 overflow-y-auto tactical-scrollbar -mx-1 px-1">
              {saved.map((video) => (
                <button
                  key={video.workflow_id}
                  type="button"
                  onClick={() => onOpenVideo(video.workflow_id)}
                  className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-secondary transition-colors"
                >
                  <div className="relative w-16 h-9 shrink-0 rounded-md border border-border bg-secondary overflow-hidden flex items-center justify-center">
                    {video.status === "completed" && video.poster_url ? (
                      <>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={video.poster_url} alt="" className="w-full h-full object-cover" />
                        {video.duration_s ? (
                          <span className="absolute bottom-0.5 right-0.5 rounded bg-black/70 px-1 text-[9px] text-white">
                            {formatDuration(video.duration_s)}
                          </span>
                        ) : null}
                      </>
                    ) : video.status === "processing" ? (
                      <span className="w-4 h-4 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
                    ) : (
                      <span className="text-xs text-red-500">!</span>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm text-foreground truncate">
                      {video.status === "processing"
                        ? "Generating…"
                        : video.status === "failed"
                          ? "Generation failed"
                          : video.title}
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      {video.document_count} {video.document_count === 1 ? "source" : "sources"}
                      {video.settings?.format && <span className="capitalize"> · {video.settings.format}</span>}
                      {video.created_at && ` · ${formatDate(video.created_at)}`}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
