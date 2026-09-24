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
  slideDeckApi,
  SlideDeckFormat,
  SlideDeckLength,
  SlideDeckOptions,
  SlideDeckStyle,
} from "@/lib/api/slideDeck";
import Segmented from "./Segmented";

interface SlideDeckSetupDialogProps {
  open: boolean;
  documentCount: number;
  onClose: () => void;
  onGenerate: (options: SlideDeckOptions) => void;
  onOpenDeck: (workflowId: string) => void;
}

const FORMAT_OPTIONS: { value: SlideDeckFormat; label: string }[] = [
  { value: "detailed", label: "Detailed deck" },
  { value: "presenter", label: "Presenter slides" },
];

const LENGTH_OPTIONS: { value: SlideDeckLength; label: string; hint: string }[] = [
  { value: "short", label: "Short", hint: "6-8" },
  { value: "default", label: "Default", hint: "10-12" },
  { value: "long", label: "Long", hint: "15-18" },
];

const STYLE_OPTIONS: { value: SlideDeckStyle; label: string }[] = [
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

export default function SlideDeckSetupDialog({
  open,
  documentCount,
  onClose,
  onGenerate,
  onOpenDeck,
}: SlideDeckSetupDialogProps) {
  const [format, setFormat] = useState<SlideDeckFormat>("detailed");
  const [length, setLength] = useState<SlideDeckLength>("default");
  const [style, setStyle] = useState<SlideDeckStyle>("auto");
  const [focus, setFocus] = useState("");

  const { data: saved, isLoading: isLoadingSaved } = useQuery({
    queryKey: ["slideDecks"],
    queryFn: slideDeckApi.list,
    enabled: open,
    // Keep refreshing while anything is still generating
    refetchInterval: (query) =>
      open && query.state.data?.some((d) => d.status === "processing") ? 4000 : false,
  });

  const handleGenerate = () => {
    onGenerate({ format, length, style, focus: focus.trim() || undefined });
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Slide deck</DialogTitle>
          <DialogDescription>
            {documentCount > 0
              ? `An editable PowerPoint deck from ${documentCount} selected ${documentCount === 1 ? "source" : "sources"}.`
              : "Select documents to generate a new deck, or open a saved one."}
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
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">
              {format === "detailed"
                ? "Self-contained slides you can read on their own."
                : "Clean, visual slides with talking points in the speaker notes."}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-foreground">Length</label>
            <Segmented options={LENGTH_OPTIONS} value={length} onChange={setLength} />
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
            <label htmlFor="deck-focus" className="text-xs font-medium text-foreground">
              What should it focus on? <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <textarea
              id="deck-focus"
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              maxLength={500}
              rows={2}
              placeholder="e.g. Brief the recovery plan for battalion leadership"
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

        {/* Saved decks */}
        <div className="border-t border-border pt-3">
          <h3 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground mb-2">Recent decks</h3>
          {isLoadingSaved ? (
            <p className="text-xs text-muted-foreground">Loading…</p>
          ) : !saved || saved.length === 0 ? (
            <p className="text-xs text-muted-foreground">No slide decks yet.</p>
          ) : (
            <div className="flex max-h-56 flex-col gap-1 overflow-y-auto tactical-scrollbar -mx-1 px-1">
              {saved.map((deck) => (
                <button
                  key={deck.workflow_id}
                  type="button"
                  onClick={() => onOpenDeck(deck.workflow_id)}
                  className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-secondary transition-colors"
                >
                  <div className="w-16 h-9 shrink-0 rounded-md border border-border bg-secondary overflow-hidden flex items-center justify-center">
                    {deck.status === "completed" && deck.thumbnail_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={deck.thumbnail_url} alt="" className="w-full h-full object-cover" />
                    ) : deck.status === "processing" ? (
                      <span className="w-4 h-4 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
                    ) : (
                      <span className="text-xs text-red-500">!</span>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm text-foreground truncate">
                      {deck.status === "processing"
                        ? "Generating…"
                        : deck.status === "failed"
                          ? "Generation failed"
                          : deck.title}
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      {deck.status === "completed" && `${deck.slide_count} slides · `}
                      {deck.document_count} {deck.document_count === 1 ? "source" : "sources"}
                      {deck.created_at && ` · ${formatDate(deck.created_at)}`}
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
