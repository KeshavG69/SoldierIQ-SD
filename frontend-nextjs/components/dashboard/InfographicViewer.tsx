"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { infographicApi } from "@/lib/api/infographic";

interface InfographicViewerProps {
  workflowId: string;
  onClose: () => void;
  /** Called with the new workflow id after "Regenerate" starts a fresh generation */
  onSwitch: (workflowId: string) => void;
}

export default function InfographicViewer({ workflowId, onClose, onSwitch }: InfographicViewerProps) {
  const [zoomed, setZoomed] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["infographic", workflowId],
    queryFn: () => infographicApi.getById(workflowId),
    // Poll until the background generation finishes
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 3000 : false),
  });

  const regenerate = useMutation({
    mutationFn: () => infographicApi.regenerate(workflowId),
    onSuccess: ({ workflow_id }) => {
      queryClient.invalidateQueries({ queryKey: ["infographics"] });
      setZoomed(false);
      onSwitch(workflow_id);
    },
  });

  const status = data?.status;
  const settings = data?.settings;
  const isLandscape = settings?.orientation === "landscape";
  const isProcessing = isLoading || status === "processing";

  return (
    <Dialog open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent
        className={`${isLandscape ? "sm:max-w-5xl" : "sm:max-w-2xl"} p-0 gap-0 flex flex-col max-h-[90vh] overflow-hidden`}
      >
        {/* Header */}
        <div className="border-b border-border px-5 py-4 pr-12">
          <DialogTitle className="text-base font-semibold text-foreground truncate">
            {status === "completed" ? data?.title : "Infographic"}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground mt-0.5">
            {data ? (
              <>
                Based on {data.document_count} {data.document_count === 1 ? "source" : "sources"}
                {settings?.style && <span className="capitalize"> · {settings.style}</span>}
                {settings?.detail_level && <span className="capitalize"> · {settings.detail_level}</span>}
              </>
            ) : (
              "Loading…"
            )}
          </DialogDescription>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto tactical-scrollbar bg-muted/40">
          {isError ? (
            <div className="px-5 py-16 text-center text-sm text-muted-foreground">Couldn&apos;t load this infographic.</div>
          ) : isProcessing ? (
            <div className="px-5 py-16 flex flex-col items-center text-center">
              <div className="w-8 h-8 border-2 border-border border-t-brand rounded-full animate-spin mb-4" />
              <p className="text-sm font-medium text-foreground">Generating infographic</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-sm">
                Picking the key points and drawing the image usually takes 30–60 seconds. You can close this; it
                will keep generating and appear under Recent infographics.
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
          ) : data?.image_url ? (
            <button
              type="button"
              onClick={() => setZoomed((z) => !z)}
              className={`block w-full p-4 ${zoomed ? "cursor-zoom-out" : "cursor-zoom-in"}`}
              title={zoomed ? "Click to fit" : "Click to zoom"}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={data.image_url}
                alt={data.title ?? "Infographic"}
                className={
                  zoomed
                    ? "w-full h-auto max-w-none rounded-md"
                    : "mx-auto max-h-[62vh] w-auto max-w-full object-contain rounded-md shadow-sm"
                }
              />
            </button>
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
                  Download PNG
                </a>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
