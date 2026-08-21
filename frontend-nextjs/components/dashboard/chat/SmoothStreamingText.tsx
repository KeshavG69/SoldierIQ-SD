"use client";

import React, { useEffect, useRef, useState } from "react";
import MarkdownContent from "./MarkdownContent";

// Smoothly reveals streamed text word-by-word instead of snapping in whole
// SSE chunks. The revealed prefix is fed through the SAME markdown renderer as
// finished messages, so formatting (tables, lists, code) renders live and
// partial markdown just re-parses each frame (react-markdown tolerates it).
//
// The reveal accelerates when it falls behind the actual streamed text (so it
// never lags far behind the backend) and stays gentle once caught up.

function countWords(text: string): number {
  if (!text) return 0;
  return text.split(/(\s+)/).filter((s) => s.trim().length > 0).length;
}

function prefixByWords(text: string, wordCount: number): string {
  if (wordCount <= 0) return "";
  const tokens = text.split(/(\s+)/); // keep whitespace tokens to preserve layout
  let seen = 0;
  let out = "";
  for (const tok of tokens) {
    out += tok;
    if (tok.trim().length > 0) {
      seen += 1;
      if (seen >= wordCount) break;
    }
  }
  return out;
}

export default function SmoothStreamingText({ text }: { text: string }) {
  const [revealed, setRevealed] = useState(0);
  const revealedRef = useRef(0);
  const targetRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const textRef = useRef("");

  textRef.current = text;
  targetRef.current = countWords(text);

  useEffect(() => {
    // New message (text shrank / reset) → restart the reveal.
    if (targetRef.current < revealedRef.current) {
      revealedRef.current = 0;
      setRevealed(0);
    }

    const tick = () => {
      const target = targetRef.current;
      const current = revealedRef.current;
      if (current >= target) {
        rafRef.current = null;
        return;
      }
      // Catch up faster the further behind we are; always advance at least 1.
      const behind = target - current;
      const step = Math.max(1, Math.floor(behind / 6));
      revealedRef.current = Math.min(current + step, target);
      setRevealed(revealedRef.current);
      rafRef.current = requestAnimationFrame(tick);
    };

    if (rafRef.current == null && revealedRef.current < targetRef.current) {
      rafRef.current = requestAnimationFrame(tick);
    }

    return () => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [text]);

  const shown = prefixByWords(text, revealed);

  return (
    <div className="relative">
      <MarkdownContent content={shown} />
      <span className="streaming-caret" aria-hidden />
      <style jsx>{`
        .streaming-caret {
          display: inline-block;
          width: 7px;
          height: 1.05em;
          margin-left: 2px;
          vertical-align: text-bottom;
          border-radius: 1px;
          background: var(--brand, #6b7d3a);
          animation: siq-caret-blink 1s steps(2, start) infinite;
        }
        @keyframes siq-caret-blink {
          0%,
          100% {
            opacity: 1;
          }
          50% {
            opacity: 0;
          }
        }
      `}</style>
    </div>
  );
}
