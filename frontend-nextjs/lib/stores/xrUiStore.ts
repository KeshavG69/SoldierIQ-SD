import { create } from "zustand";

export type XRScreen =
  | "home"
  | "documents"
  | "quiz"
  | "slides"
  | "flashcards"
  | "infographic"
  | "mindmap"
  | "video"
  | "audio"
  | "reports";

/**
 * Gesture hooks the active screen exposes. Each returns true when it handled the
 * gesture, so the controller can fall back to a default (e.g. thumbs → voice feedback).
 */
export interface XRScreenHandlers {
  next?: () => boolean | void; // swipe right
  prev?: () => boolean | void; // swipe left
  choose?: (n: 1 | 2 | 3 | 4) => boolean | void; // fingers held up
  confirm?: () => boolean | void; // thumbs up
  back?: () => boolean | void; // swipe down
}

interface Toast {
  id: number;
  text: string;
}

interface XRUiState {
  screen: XRScreen;
  handlers: XRScreenHandlers | null;
  toast: Toast | null;
  /** While `Date.now()` < this, a second "stop" ends the voice session. */
  confirmStopUntil: number;
  /** Bumped to ask the panel rig to recenter in front of the user. */
  recenterNonce: number;
  rigScale: number;
  setScreen: (screen: XRScreen) => void;
  setHandlers: (handlers: XRScreenHandlers | null) => void;
  showToast: (text: string) => void;
  setConfirmStopUntil: (t: number) => void;
  recenter: () => void;
  setRigScale: (s: number) => void;
}

let toastId = 0;

export const useXRUi = create<XRUiState>((set) => ({
  screen: "home",
  handlers: null,
  toast: null,
  confirmStopUntil: 0,
  recenterNonce: 0,
  rigScale: 1,
  setScreen: (screen) => set({ screen }),
  setHandlers: (handlers) => set({ handlers }),
  showToast: (text) => set({ toast: { id: ++toastId, text } }),
  setConfirmStopUntil: (confirmStopUntil) => set({ confirmStopUntil }),
  recenter: () => set((s) => ({ recenterNonce: s.recenterNonce + 1 })),
  setRigScale: (rigScale) => set({ rigScale: Math.min(2, Math.max(0.5, rigScale)) }),
}));
