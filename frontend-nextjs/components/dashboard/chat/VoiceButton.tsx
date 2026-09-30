"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";

import { LiveDictation } from "@/lib/voice/liveDictation";

/**
 * Mic button next to Send in ChatInput: live dictation into the message box.
 * Click to start; the text appears in the input as you speak (updated about
 * once a second, finalised at each pause); click again to stop. Transcription
 * is Deepgram Nova-3 via OpenRouter (lib/voice/liveDictation.ts).
 *
 * The LiveKit voice-agent call this button used to start is commented out
 * (components/dashboard/VoiceSession.tsx).
 */

export type DictationState = "idle" | "starting" | "listening" | "finishing";

interface VoiceButtonProps {
  disabled?: boolean;
  /** Current input text — dictated text is appended to it. */
  value: string;
  onChange: (value: string) => void;
  onStateChange?: (state: DictationState, error?: string | null) => void;
}

const MAX_DICTATION_MS = 5 * 60 * 1000; // same cap as Claude's dictation

function join(base: string, dictated: string): string {
  if (!dictated) return base;
  if (!base.trim()) return dictated;
  return `${base.replace(/\s+$/, "")} ${dictated}`;
}

const VoiceButton = React.memo(function VoiceButton({ disabled, value, onChange, onStateChange }: VoiceButtonProps) {
  const [state, setState] = useState<DictationState>("idle");
  const [level, setLevel] = useState(0);
  const dictationRef = useRef<LiveDictation | null>(null);
  const baseRef = useRef("");
  const capTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;

  const update = useCallback(
    (next: DictationState, error: string | null = null) => {
      setState(next);
      onStateChange?.(next, error);
    },
    [onStateChange]
  );

  const stop = useCallback(async () => {
    const d = dictationRef.current;
    if (!d) return;
    if (capTimer.current) clearTimeout(capTimer.current);
    update("finishing");
    const text = await d.stop();
    dictationRef.current = null;
    onChange(join(baseRef.current, text));
    setLevel(0);
    update("idle");
  }, [onChange, update]);

  const start = useCallback(async () => {
    if (dictationRef.current) return;
    baseRef.current = valueRef.current;
    update("starting");
    const d = new LiveDictation({
      onText: (text) => onChange(join(baseRef.current, text)),
      onLevel: setLevel,
      onError: (msg) => onStateChange?.("listening", msg),
    });
    dictationRef.current = d;
    try {
      await d.start();
      update("listening");
      capTimer.current = setTimeout(() => stop(), MAX_DICTATION_MS);
    } catch (e: any) {
      d.cancel();
      dictationRef.current = null;
      const denied = e?.name === "NotAllowedError" || e?.name === "SecurityError";
      update("idle", denied ? "Microphone access was blocked. Allow it in your browser to dictate." : "Couldn't start the microphone.");
    }
  }, [onChange, onStateChange, stop, update]);

  // Stop the mic if the input unmounts mid-dictation.
  useEffect(() => () => {
    if (capTimer.current) clearTimeout(capTimer.current);
    dictationRef.current?.cancel();
  }, []);

  const listening = state === "listening";
  const busy = state === "starting" || state === "finishing";

  return (
    <button
      type="button"
      onClick={listening ? stop : start}
      disabled={(disabled && !listening) || busy}
      aria-label={listening ? "Stop dictation" : "Dictate"}
      aria-pressed={listening}
      title={listening ? "Stop dictation" : "Dictate — speak and your words appear here"}
      className={`absolute right-11 bottom-2 w-8 h-8 rounded-lg flex items-center justify-center transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        listening
          ? "bg-red-500/15 text-red-500 hover:bg-red-500/25"
          : "text-muted-foreground hover:text-foreground hover:bg-secondary dark:hover:bg-accent"
      }`}
    >
      {busy ? (
        <div className="w-3.5 h-3.5 border-2 border-current/30 border-t-current rounded-full animate-spin" />
      ) : listening ? (
        <span className="relative flex items-center justify-center">
          {/* Level ring grows with your voice */}
          <span
            className="absolute rounded-full bg-red-500/25 transition-transform duration-75"
            style={{ width: 28, height: 28, transform: `scale(${0.55 + level * 0.6})` }}
            aria-hidden
          />
          <Square className="relative w-3 h-3 fill-current" />
        </span>
      ) : (
        <Mic className="w-4 h-4" />
      )}
    </button>
  );
});

export default VoiceButton;
