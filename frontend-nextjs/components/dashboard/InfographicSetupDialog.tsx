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
  infographicApi,
  InfographicDetailLevel,
  InfographicOptions,
  InfographicOrientation,
  InfographicStyle,
} from "@/lib/api/infographic";
import Segmented from "./Segmented";

interface InfographicSetupDialogProps {
  open: boolean;
  documentCount: number;
  onClose: () => void;
  onGenerate: (options: InfographicOptions) => void;
  onOpenInfographic: (workflowId: string) => void;
}

const ORIENTATION_OPTIONS: { value: InfographicOrientation; label: string }[] = [
  { value: "portrait", label: "Portrait" },
  { value: "landscape", label: "Landscape" },
  { value: "square", label: "Square" },
];

const DETAIL_OPTIONS: { value: InfographicDetailLevel; label: string }[] = [
  { value: "concise", label: "Concise" },
  { value: "standard", label: "Standard" },
  { value: "detailed", label: "Detailed" },
];

const STYLE_OPTIONS: { value: InfographicStyle; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "professional", label: "Professional" },
  { value: "tactical", label: "Tactical" },
  { value: "editorial", label: "Editorial" },
  { value: "instructional", label: "Instructional" },
  { value: "sketch", label: "Sketch note" },
];

function formatDate(iso: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function InfographicSetupDialog({
  open,
  documentCount,
  onClose,
  onGenerate,
  onOpenInfographic,
}: InfographicSetupDialogProps) {
  const [orientation, setOrientation] = useState<InfographicOrientation>("portrait");
  const [detailLevel, setDetailLevel] = useState<InfographicDetailLevel>("standard");
  const [style, setStyle] = useState<InfographicStyle>("auto");
  const [focus, setFocus] = useState("");

  const { data: saved, isLoading: isLoadingSaved } = useQuery({
    queryKey: ["infographics"],
    queryFn: infographicApi.list,
    enabled: open,
    // Keep refreshing while anything is still generating
    refetchInterval: (query) =>
      open && query.state.data?.some((i) => i.status === "processing") ? 3000 : false,
  });

  const handleGenerate = () => {
    onGenerate({
      orientation,
      detail_level: detailLevel,
      style,
      focus: focus.trim() || undefined,
    });
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Infographic</DialogTitle>
          <DialogDescription>
            {documentCount > 0
              ? `A visual summary of ${documentCount} selected ${documentCount === 1 ? "source" : "sources"}.`
              : "Select documents to generate a new infographic, or open a saved one."}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-foreground">Orientation</label>
            <Segmented options={ORIENTATION_OPTIONS} value={orientation} onChange={setOrientation} />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-foreground">Level of detail</label>
            <Segmented options={DETAIL_OPTIONS} value={detailLevel} onChange={setDetailLevel} />
            {detailLevel === "detailed" && (
              <p className="text-[11px] text-muted-foreground">More text means a higher chance of spelling slips in the image.</p>
            )}
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
            <label htmlFor="infographic-focus" className="text-xs font-medium text-foreground">
              What should it focus on? <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <textarea
              id="infographic-focus"
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              maxLength={500}
              rows={2}
              placeholder="e.g. Highlight the recovery timeline and key equipment figures"
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

        {/* Saved infographics */}
        <div className="border-t border-border pt-3">
          <h3 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground mb-2">
            Recent infographics
          </h3>
          {isLoadingSaved ? (
            <p className="text-xs text-muted-foreground">Loading…</p>
          ) : !saved || saved.length === 0 ? (
            <p className="text-xs text-muted-foreground">No infographics yet.</p>
          ) : (
            <div className="flex max-h-56 flex-col gap-1 overflow-y-auto tactical-scrollbar -mx-1 px-1">
              {saved.map((item) => (
                <button
                  key={item.workflow_id}
                  type="button"
                  onClick={() => onOpenInfographic(item.workflow_id)}
                  className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-secondary transition-colors"
                >
                  <div className="w-10 h-10 shrink-0 rounded-md border border-border bg-secondary overflow-hidden flex items-center justify-center">
                    {item.status === "completed" && item.image_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={item.image_url} alt="" className="w-full h-full object-cover" />
                    ) : item.status === "processing" ? (
                      <span className="w-4 h-4 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
                    ) : (
                      <span className="text-xs text-red-500">!</span>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm text-foreground truncate">
                      {item.status === "processing"
                        ? "Generating…"
                        : item.status === "failed"
                          ? "Generation failed"
                          : item.title}
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      {item.document_count} {item.document_count === 1 ? "source" : "sources"}
                      {item.settings?.style && <span className="capitalize"> · {item.settings.style}</span>}
                      {item.created_at && ` · ${formatDate(item.created_at)}`}
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
