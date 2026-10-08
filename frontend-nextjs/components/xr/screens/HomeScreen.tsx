"use client";

import { useXRStore } from "@react-three/xr";

import { Button, C, SCREEN_H, SCREEN_W, T, useScreenHandlers } from "../ui";
import { useXRUi, type XRScreen } from "@/lib/stores/xrUiStore";
import { useDocumentStore } from "@/lib/stores/documentStore";

const TILES: { screen: XRScreen; title: string; hint: string }[] = [
  { screen: "documents", title: "Documents", hint: "Choose sources" },
  { screen: "quiz", title: "Quiz", hint: "Fingers pick A–D" },
  { screen: "slides", title: "Slide deck", hint: "Swipe slides" },
  { screen: "flashcards", title: "Flashcards", hint: "Pinch to flip" },
  { screen: "infographic", title: "Infographic", hint: "Big-screen view" },
  { screen: "mindmap", title: "Mind map", hint: "Pinch to explore" },
  { screen: "video", title: "Video overview", hint: "Swipe chapters" },
  { screen: "audio", title: "Audio overview", hint: "Podcast player" },
  { screen: "reports", title: "Reports", hint: "Swipe pages" },
];

const COLS = 3;

export default function HomeScreen() {
  const setScreen = useXRUi((s) => s.setScreen);
  const selected = useDocumentStore((s) => s.selectedDocs.size);
  const store = useXRStore();

  useScreenHandlers({});

  const tileW = 0.29;
  const tileH = 0.12;
  return (
    <group>
      <T position={[-SCREEN_W / 2 + 0.04, SCREEN_H / 2 - 0.05, 0]} anchorX="left" fontSize={0.03}>
        SoldierIQ
      </T>
      <T position={[-SCREEN_W / 2 + 0.04, SCREEN_H / 2 - 0.088, 0]} anchorX="left" fontSize={0.016} color={C.muted}>
        {`${selected} document${selected === 1 ? "" : "s"} selected · swipe up anytime to come back here`}
      </T>
      <Button
        label="Exit VR"
        width={0.12}
        height={0.042}
        position={[SCREEN_W / 2 - 0.085, SCREEN_H / 2 - 0.055, 0]}
        onClick={() => void store.getState().session?.end()}
      />
      {TILES.map((tile, i) => {
        const col = i % COLS;
        const row = Math.floor(i / COLS);
        const x = (col - (COLS - 1) / 2) * (tileW + 0.025);
        const y = SCREEN_H / 2 - 0.2 - row * (tileH + 0.025);
        return (
          <group key={tile.screen} position={[x, y, 0]}>
            <Button label="" width={tileW} height={tileH} position={[0, 0, 0]} onClick={() => setScreen(tile.screen)} />
            <T position={[0, 0.018, 0.01]} fontSize={0.022}>
              {tile.title}
            </T>
            <T position={[0, -0.022, 0.01]} fontSize={0.014} color={C.muted}>
              {tile.hint}
            </T>
          </group>
        );
      })}
    </group>
  );
}
