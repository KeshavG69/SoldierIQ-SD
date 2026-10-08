"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { RoundedBox } from "@react-three/drei";

import { Busy, Button, C, SCREEN_H, SCREEN_W, ScreenHeader, T, usePager, useScreenHandlers } from "../ui";
import { flashcardsApi, type FlashcardData } from "@/lib/api/flashcards";
import { useDocumentStore } from "@/lib/stores/documentStore";
import { useXRUi } from "@/lib/stores/xrUiStore";

export default function FlashcardsScreen() {
  const [deck, setDeck] = useState<FlashcardData | null>(null);
  if (deck) return <CardViewer deck={deck} onExit={() => setDeck(null)} />;
  return <GenerateDeck onReady={setDeck} />;
}

function GenerateDeck({ onReady }: { onReady: (deck: FlashcardData) => void }) {
  const selectedDocs = useDocumentStore((s) => s.selectedDocs);
  const setScreen = useXRUi((s) => s.setScreen);

  const generate = useMutation({
    mutationFn: () => flashcardsApi.generate(Array.from(selectedDocs)),
    onSuccess: onReady,
  });
  const start = () => {
    if (selectedDocs.size === 0 || generate.isPending) return false;
    generate.mutate();
    return true;
  };

  useScreenHandlers({ confirm: start });

  return (
    <group>
      <ScreenHeader title="Flashcards" subtitle="Study cards generated from your selected documents" />
      {generate.isPending ? (
        <Busy text="Writing flashcards… this can take a minute" />
      ) : (
        <group>
          <T position={[0, 0.08, 0]} fontSize={0.022} color={C.muted} maxWidth={SCREEN_W - 0.2} textAlign="center">
            {selectedDocs.size > 0
              ? `Generate a deck from ${selectedDocs.size} selected document${selectedDocs.size === 1 ? "" : "s"}.`
              : "Select documents first."}
          </T>
          {generate.isError && (
            <T position={[0, 0.02, 0]} fontSize={0.016} color={C.danger}>
              Flashcard generation failed - try again.
            </T>
          )}
          <Button
            label={selectedDocs.size > 0 ? "Generate flashcards" : "Select documents"}
            width={0.3}
            color={C.accent}
            position={[0, -0.06, 0]}
            onClick={() => (selectedDocs.size > 0 ? start() : setScreen("documents"))}
          />
        </group>
      )}
    </group>
  );
}

function CardViewer({ deck, onExit }: { deck: FlashcardData; onExit: () => void }) {
  const [flipped, setFlipped] = useState(false);
  const pager = usePager(deck.cards.length);
  const card = deck.cards[pager.page];

  const go = (move: () => boolean) => () => {
    const moved = move();
    if (moved) setFlipped(false);
    return moved;
  };
  const flip = () => {
    setFlipped((f) => !f);
    return true;
  };

  useScreenHandlers({
    next: go(pager.next),
    prev: go(pager.prev),
    confirm: flip,
    back: () => {
      onExit();
      return true;
    },
  });

  const cardW = 0.78;
  const cardH = 0.4;
  return (
    <group>
      <ScreenHeader
        title={deck.title}
        subtitle={`Card ${pager.page + 1} of ${deck.cards.length} · pinch or thumbs up to flip · swipe for next`}
        onBack={onExit}
        backLabel="New deck"
      />
      <group position={[0, -0.03, 0.004]}>
        <RoundedBox
          args={[cardW, cardH, 0.012]}
          radius={0.02}
          onClick={(e) => {
            e.stopPropagation();
            flip();
          }}
        >
          <meshBasicMaterial color={flipped ? "#14283f" : "#1b1f26"} />
        </RoundedBox>
        <T position={[0, cardH / 2 - 0.035, 0.01]} fontSize={0.014} color={flipped ? C.accent : C.muted}>
          {flipped ? "ANSWER" : "QUESTION"}
        </T>
        <T position={[0, -0.01, 0.01]} fontSize={0.026} maxWidth={cardW - 0.08} textAlign="center">
          {flipped ? card?.back : card?.front}
        </T>
      </group>
      <Button label="<" width={0.06} position={[-SCREEN_W / 2 + 0.06, -SCREEN_H / 2 + 0.04, 0]} disabled={pager.page === 0} onClick={go(pager.prev)} />
      <Button label="Flip" width={0.1} position={[0, -SCREEN_H / 2 + 0.04, 0]} onClick={flip} />
      <Button
        label=">"
        width={0.06}
        position={[SCREEN_W / 2 - 0.06, -SCREEN_H / 2 + 0.04, 0]}
        disabled={pager.page >= deck.cards.length - 1}
        onClick={go(pager.next)}
      />
    </group>
  );
}
