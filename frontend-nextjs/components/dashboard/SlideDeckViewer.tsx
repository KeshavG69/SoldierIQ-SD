"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { slideDeckApi, SlideDeckStage } from "@/lib/api/slideDeck";

interface SlideDeckViewerProps {
  workflowId: string;
  onClose: () => void;
  /** Called with the new workflow id after "Regenerate" starts a fresh generation */
  onSwitch: (workflowId: string) => void;
}

const STAGES: { key: SlideDeckStage; label: string }[] = [
  { key: "reading", label: "Reading your documents" },
  { key: "designing", label: "Designing and building the slides" },
  { key: "rendering", label: "Rendering the preview" },
];

export default function SlideDeckViewer({ workflowId, onClose, onSwitch }: SlideDeckViewerProps) {
  const [current, setCurrent] = useState(0);
  const [showNotes, setShowNotes] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["slideDeck", workflowId],
    queryFn: () => slideDeckApi.getById(workflowId),
    // Poll until the background generation finishes
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 4000 : false),
  });

  const regenerate = useMutation({
    mutationFn: () => slideDeckApi.regenerate(workflowId),
    onSuccess: ({ workflow_id }) => {
      queryClient.invalidateQueries({ queryKey: ["slideDecks"] });
      onSwitch(workflow_id);
    },
  });

  const status = data?.status;
  const slides = data?.slide_urls ?? [];
  const total = slides.length;
  const isProcessing = isLoading || status === "processing";
  const stageIndex = STAGES.findIndex((s) => s.key === data?.stage);

  const goTo = (index: number) => {
    if (index >= 0 && index < total) setCurrent(index);
  };

  // Arrow-key navigation (capture phase: the Dialog stops arrow keys before they bubble)
  useEffect(() => {
    if (status !== "completed") return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setCurrent((c) => Math.max(0, c - 1));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        setCurrent((c) => Math.min(total - 1, c + 1));
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [status, total]);

  return (
    <Dialog open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-5xl p-0 gap-0 flex flex-col max-h-[92vh] overflow-hidden">
        {/* Header */}
        <div className="border-b border-border px-5 py-4 pr-12">
          <DialogTitle className="text-base font-semibold text-foreground truncate">
            {status === "completed" ? data?.title : "Slide deck"}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground mt-0.5">
            {data ? (
              <>
                {status === "completed" && `${total} slides · `}
                Based on {data.document_count} {data.document_count === 1 ? "source" : "sources"}
                {data.settings?.format && (
                  <span> · {data.settings.format === "presenter" ? "Presenter slides" : "Detailed deck"}</span>
                )}
                {data.settings?.style && <span className="capitalize"> · {data.settings.style}</span>}
              </>
            ) : (
              "Loading…"
            )}
          </DialogDescription>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto tactical-scrollbar bg-muted/40">
          {isError ? (
            <div className="px-5 py-16 text-center text-sm text-muted-foreground">Couldn&apos;t load this slide deck.</div>
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
                An AI designer is building an editable PowerPoint for you. This usually takes 2–5 minutes. You can close
                this; it keeps going and appears under Recent decks.
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
          ) : total > 0 ? (
            <div className="p-4 flex flex-col gap-3">
              {/* Current slide */}
              <div className="relative group">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={slides[current]}
                  alt={`Slide ${current + 1}`}
                  className="w-full aspect-video object-contain rounded-md shadow-sm bg-white"
                />
                <button
                  type="button"
                  onClick={() => goTo(current - 1)}
                  disabled={current === 0}
                  className="absolute left-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-black/50 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 disabled:!opacity-0 transition-opacity"
                  title="Previous (←)"
                >
                  ‹
                </button>
                <button
                  type="button"
                  onClick={() => goTo(current + 1)}
                  disabled={current === total - 1}
                  className="absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-black/50 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 disabled:!opacity-0 transition-opacity"
                  title="Next (→)"
                >
                  ›
                </button>
                <span className="absolute bottom-2 right-2 rounded-md bg-black/55 px-2 py-0.5 text-[11px] text-white">
                  {current + 1} / {total}
                </span>
              </div>

              {/* Speaker notes */}
              {data?.notes?.[current] && (
                <div>
                  <button
                    type="button"
                    onClick={() => setShowNotes((s) => !s)}
                    className="text-xs text-brand hover:underline"
                  >
                    {showNotes ? "Hide speaker notes" : "Show speaker notes"}
                  </button>
                  {showNotes && (
                    <p className="mt-1.5 rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground whitespace-pre-line">
                      {data.notes[current]}
                    </p>
                  )}
                </div>
              )}

              {/* Thumbnails */}
              <div className="flex gap-2 overflow-x-auto tactical-scrollbar pb-1">
                {slides.map((url, i) => (
                  <button
                    key={url}
                    type="button"
                    onClick={() => goTo(i)}
                    className={`shrink-0 w-28 rounded-md overflow-hidden border-2 transition-colors ${
                      i === current ? "border-brand" : "border-transparent hover:border-border"
                    }`}
                    title={`Slide ${i + 1}`}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={url} alt="" className="w-full aspect-video object-cover bg-white" />
                  </button>
                ))}
              </div>
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
              {data?.pdf_url && (
                <a
                  href={data.pdf_url}
                  className="inline-flex h-8 items-center rounded-lg border border-border px-2.5 text-sm font-medium text-foreground hover:bg-muted transition-colors"
                >
                  Download PDF
                </a>
              )}
              {data?.pptx_url && (
                <a
                  href={data.pptx_url}
                  className="inline-flex h-8 items-center rounded-lg bg-primary px-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/80 transition-colors"
                >
                  Download PPTX
                </a>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
