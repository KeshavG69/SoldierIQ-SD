"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Busy,
  Button,
  C,
  MediaImage,
  SCREEN_H,
  SCREEN_W,
  SavedList,
  ScreenHeader,
  T,
  fmtDate,
  usePager,
  useScreenHandlers,
} from "../ui";
import { slideDeckApi, type SlideDeckStage } from "@/lib/api/slideDeck";
import { useDocumentStore } from "@/lib/stores/documentStore";

const STAGE_TEXT: Partial<Record<SlideDeckStage, string>> = {
  queued: "Queued…",
  reading: "Reading your documents…",
  designing: "Designing and building the slides…",
  rendering: "Rendering the slides…",
};

export default function SlidesScreen() {
  const [deckId, setDeckId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedDocs = useDocumentStore((s) => s.selectedDocs);
  const queryClient = useQueryClient();

  const list = useQuery({ queryKey: ["slideDecks"], queryFn: slideDeckApi.list, enabled: !deckId });
  const generate = useMutation({
    mutationFn: () =>
      slideDeckApi.generate(Array.from(selectedDocs), { format: "detailed", length: "default", style: "auto" }),
    onSuccess: ({ workflow_id }) => {
      queryClient.invalidateQueries({ queryKey: ["slideDecks"] });
      setDeckId(workflow_id);
    },
    onError: () => setError("Could not start slide deck generation."),
  });

  if (deckId) return <DeckViewer deckId={deckId} onExit={() => setDeckId(null)} />;

  return (
    <group>
      <ScreenHeader title="Slide deck" subtitle="Open a deck or generate one from your selected documents" />
      <SavedList
        items={(list.data ?? []).map((d) => ({
          id: d.workflow_id,
          title: d.title ?? "Untitled deck",
          subtitle:
            d.status === "completed"
              ? `${d.slide_count} slides · ${fmtDate(d.created_at)}`
              : d.status === "processing"
                ? "generating…"
                : "failed",
          disabled: d.status === "failed",
        }))}
        loading={list.isLoading}
        onOpen={setDeckId}
        onGenerate={() => {
          setError(null);
          generate.mutate();
        }}
        generating={generate.isPending}
        generateLabel="Generate slide deck"
        canGenerate={selectedDocs.size > 0}
        emptyText="No slide decks yet."
        error={error}
      />
    </group>
  );
}

function DeckViewer({ deckId, onExit }: { deckId: string; onExit: () => void }) {
  const [showNotes, setShowNotes] = useState(false);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["slideDeck", deckId],
    queryFn: () => slideDeckApi.getById(deckId),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 4000 : false),
  });

  const slides = data?.status === "completed" ? data.slide_urls : [];
  const pager = usePager(slides.length, deckId);

  useScreenHandlers({
    next: pager.next,
    prev: pager.prev,
    confirm: () => {
      setShowNotes((v) => !v);
      return true;
    },
    back: () => {
      onExit();
      return true;
    },
  });

  const title = data?.title ?? "Slide deck";

  if (isLoading || data?.status === "processing") {
    return (
      <group>
        <ScreenHeader title={title} subtitle="Generating - this usually takes a few minutes" onBack={onExit} backLabel="All decks" />
        <Busy text={(data?.stage && STAGE_TEXT[data.stage]) || "Starting…"} />
      </group>
    );
  }
  if (isError || data?.status === "failed" || slides.length === 0) {
    return (
      <group>
        <ScreenHeader title={title} onBack={onExit} backLabel="All decks" />
        <T fontSize={0.02} color={C.danger} maxWidth={SCREEN_W - 0.1}>
          {data?.error || "This deck could not be loaded."}
        </T>
      </group>
    );
  }

  const notes = data?.notes?.[pager.page];
  const imageH = showNotes ? 0.34 : 0.5;
  return (
    <group>
      <ScreenHeader title={title} subtitle={`Slide ${pager.page + 1} of ${slides.length} · swipe to change · thumbs up for notes`} onBack={onExit} backLabel="All decks" />
      <MediaImage url={slides[pager.page]} maxW={SCREEN_W - 0.06} maxH={imageH} position={[0, showNotes ? 0.05 : -0.03, 0.002]} />
      {showNotes && (
        <T position={[-SCREEN_W / 2 + 0.04, -0.21, 0]} anchorX="left" anchorY="top" fontSize={0.015} color={C.muted} maxWidth={SCREEN_W - 0.08}>
          {notes ? notes.slice(0, 500) : "No speaker notes for this slide."}
        </T>
      )}
      <Button label="<" width={0.06} position={[-SCREEN_W / 2 + 0.06, -SCREEN_H / 2 + 0.04, 0]} disabled={pager.page === 0} onClick={pager.prev} />
      <Button label="Notes" width={0.1} position={[0, -SCREEN_H / 2 + 0.04, 0]} onClick={() => setShowNotes((v) => !v)} />
      <Button label=">" width={0.06} position={[SCREEN_W / 2 - 0.06, -SCREEN_H / 2 + 0.04, 0]} disabled={pager.page >= slides.length - 1} onClick={pager.next} />
    </group>
  );
}
