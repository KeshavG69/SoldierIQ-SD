"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Canvas } from "@react-three/fiber";
import { XR, createXRStore } from "@react-three/xr";
import { ArrowLeft, Glasses } from "lucide-react";

import XRScene from "./XRScene";
import XRVoiceRoom from "./XRVoiceRoom";
import { useAuthStore } from "@/lib/stores/authStore";
import { useDocumentStore } from "@/lib/stores/documentStore";
import { useVoiceStore } from "@/lib/stores/voiceStore";
import { useDocuments } from "@/lib/hooks/useDocuments";

// Hands render with the default pinch ray pointer, so panel buttons are clickable by pinching.
const xrStore = createXRStore({ handTracking: true, offerSession: false });

const GESTURES: { gesture: string; action: string }[] = [
  { gesture: "Point + pinch", action: "Click anything" },
  { gesture: "Swipe left / right", action: "Next / previous (slides, cards, pages)" },
  { gesture: "Swipe up", action: "Home (all screens)" },
  { gesture: "Swipe down", action: "Back" },
  { gesture: "Hold up 1-4 fingers", action: "Pick answer / list row" },
  { gesture: "Thumbs up", action: "Submit, flip card, play / pause" },
  { gesture: "Open palm toward you (1 s)", action: "Start the voice agent" },
  { gesture: "Finger to lips", action: "Mute / unmute your mic" },
  { gesture: "Quick fist", action: "Interrupt the agent" },
  { gesture: "Thumbs down", action: "Ask the agent to retry" },
  { gesture: "Both palms out", action: "End voice session (twice)" },
  { gesture: "Fist held 2 s", action: "Recenter panels" },
  { gesture: "Two-hand pinch + pull", action: "Resize panels" },
];

export default function XRWorkspace() {
  const router = useRouter();
  const debug = useSearchParams().get("debug") === "1";
  const user = useAuthStore((s) => s.user);
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const selectedDocs = useDocumentStore((s) => s.selectedDocs);
  const { data: documents = [] } = useDocuments(user?.organization_id);
  const startVoice = useVoiceStore((s) => s.start);

  const [support, setSupport] = useState<"checking" | "ar" | "vr" | "none">("checking");
  const [enterError, setEnterError] = useState<string | null>(null);

  useEffect(() => {
    if (!isInitializing && !user) router.push("/auth/login");
  }, [user, isInitializing, router]);

  useEffect(() => {
    const xr = typeof navigator !== "undefined" ? navigator.xr : undefined;
    if (!xr) return setSupport("none");
    (async () => {
      if (await xr.isSessionSupported("immersive-ar").catch(() => false)) return setSupport("ar");
      if (await xr.isSessionSupported("immersive-vr").catch(() => false)) return setSupport("vr");
      setSupport("none");
    })();
  }, []);

  const selectedNames = useMemo(
    () => documents.filter((d) => selectedDocs.has(d.id)).map((d) => d.file_name),
    [documents, selectedDocs],
  );

  const onStartVoice = useCallback(() => {
    if (useVoiceStore.getState().state !== "idle") return;
    void startVoice({ document_ids: Array.from(selectedDocs), file_names: selectedNames });
  }, [startVoice, selectedDocs, selectedNames]);

  const enter = async () => {
    setEnterError(null);
    try {
      // Permission prompts can't be shown inside an immersive session, so ask for the mic first.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
    } catch {
      setEnterError("Microphone access is needed for the voice agent.");
      return;
    }
    try {
      if (support === "ar") await xrStore.enterAR();
      else await xrStore.enterVR();
    } catch (err) {
      setEnterError(err instanceof Error ? err.message : "Could not start VR");
    }
  };

  if (!user) return null;

  return (
    <div className="relative h-dvh w-full overflow-hidden bg-[#0b0d10] text-white">
      <Canvas className="!absolute inset-0" camera={{ position: [0, 1.6, 0], rotation: [0, 0, 0], fov: 60 }}>
        <XR store={xrStore}>
          <XRScene documentCount={selectedDocs.size} onStartVoice={onStartVoice} debug={debug} />
        </XR>
      </Canvas>

      <XRVoiceRoom />

      <div className="pointer-events-none absolute inset-x-0 top-0 flex justify-between p-4">
        <Link
          href="/dashboard"
          className="pointer-events-auto flex items-center gap-2 rounded-lg bg-white/10 px-3 py-2 text-sm hover:bg-white/20"
        >
          <ArrowLeft className="h-4 w-4" /> Dashboard
        </Link>
      </div>

      <div className="absolute bottom-4 left-1/2 w-[min(560px,calc(100%-32px))] -translate-x-1/2 rounded-xl border border-white/10 bg-black/70 p-5 backdrop-blur">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold">SoldierIQ in VR</h1>
            <p className="mt-1 text-sm text-white/60">
              Quiz, slides, flashcards, reports, media and the voice agent - hands-free on Meta Quest.{" "}
              {selectedDocs.size === 0
                ? "No documents selected yet - you can pick them inside VR."
                : `${selectedDocs.size} document${selectedDocs.size === 1 ? "" : "s"} in scope.`}
            </p>
          </div>
          <button
            type="button"
            onClick={enter}
            disabled={support === "checking" || support === "none"}
            className="flex shrink-0 items-center gap-2 rounded-lg bg-[#4f8cff] px-4 py-2 text-sm font-medium hover:bg-[#3f7cf0] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Glasses className="h-4 w-4" />
            {support === "none" ? "VR not supported" : "Enter VR"}
          </button>
        </div>
        {enterError && <p className="mt-3 text-sm text-red-400">{enterError}</p>}
        {support === "none" && (
          <p className="mt-3 text-xs text-white/50">Open this page in the Meta Quest Browser to use hand gestures.</p>
        )}
        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2">
          {GESTURES.map((g) => (
            <div key={g.gesture} className="flex justify-between gap-3">
              <dt className="text-white/50">{g.gesture}</dt>
              <dd className="text-right">{g.action}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
