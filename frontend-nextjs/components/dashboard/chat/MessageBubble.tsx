"use client";

import React from "react";
import { ChatMessage } from "@/types";
import { DocumentSource } from "@/lib/stores/chatStore";
import MarkdownContent from "./MarkdownContent";
import SmoothStreamingText from "./SmoothStreamingText";

interface MessageBubbleProps {
  message: ChatMessage;
  sourceUrls: Map<string, string>;
  animationDelay: number;
  onCitationHover: (index: number, messageId: string, x: number, y: number) => void;
  onCitationLeave: () => void;
  onCitationClick: (source: DocumentSource, url: string | undefined) => void;
  onOpenGraph?: (message: ChatMessage) => void;
}

const MessageBubble = React.memo(function MessageBubble({
  message,
  sourceUrls,
  animationDelay,
  onCitationHover,
  onCitationLeave,
  onCitationClick,
  onOpenGraph,
}: MessageBubbleProps) {
  const hasGraph =
    !!message.graph &&
    ((message.graph.triples?.length ?? 0) > 0 ||
      (message.graph.anchors?.length ?? 0) > 0);
  const isUser = message.role === "user";
  const isStreaming = message.isStreaming === true;

  const timeStr = new Date(message.timestamp).toLocaleTimeString("en-US", {
    hour12: true,
    hour: "numeric",
    minute: "2-digit",
  });

  if (isUser) {
    return (
      <div
        className="data-load flex justify-end"
        style={{ animationDelay: `${animationDelay}ms` }}
      >
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-secondary dark:bg-card px-4 py-2.5">
          <div className="text-[15px] text-foreground dark:text-foreground whitespace-pre-wrap leading-relaxed">
            {message.content}
          </div>
          <div className="text-[11px] text-muted-foreground dark:text-muted-foreground mt-1 text-right">
            {timeStr}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="data-load flex justify-start"
      style={{ animationDelay: `${animationDelay}ms` }}
    >
      <div className="max-w-[92%] w-full">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-6 h-6 rounded-md bg-brand flex items-center justify-center flex-shrink-0 shadow-accent">
            <svg
              className="w-3.5 h-3.5 text-brand-foreground"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </div>
          <span className="text-xs font-medium text-foreground dark:text-foreground">
            SoldierIQ
          </span>
          <span className="text-[11px] text-muted-foreground">· {timeStr}</span>
        </div>

        <div className="pl-8">
          {message.content ? (
            isStreaming ? (
              <SmoothStreamingText text={message.content} />
            ) : (
              <MarkdownContent
                content={message.content}
                citation={{
                  message,
                  sourceUrls,
                  onCitationHover,
                  onCitationLeave,
                  onCitationClick,
                }}
              />
            )
          ) : (
            <div className="flex items-center gap-2 text-muted-foreground text-sm">
              <div className="w-3.5 h-3.5 border-2 border-border border-t-border dark:border-border dark:border-t-border rounded-full animate-spin" />
              Thinking…
            </div>
          )}

          {hasGraph && !isStreaming && onOpenGraph && (
            <button
              onClick={() => onOpenGraph(message)}
              className="mt-3 inline-flex items-center gap-1.5 text-[12px] font-medium px-2.5 py-1 rounded-md border border-border dark:border-border bg-surface-2 dark:bg-card text-muted-foreground dark:text-foreground hover:bg-secondary dark:hover:bg-accent transition-colors"
              title="See how the retrieved entities and relations connect"
            >
              <svg
                className="w-3.5 h-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="6" cy="6" r="2.5" />
                <circle cx="18" cy="6" r="2.5" />
                <circle cx="12" cy="18" r="2.5" />
                <line x1="8" y1="7" x2="16" y2="7" />
                <line x1="7" y1="8" x2="11" y2="16" />
                <line x1="17" y1="8" x2="13" y2="16" />
              </svg>
              View knowledge graph
              <span className="text-[10px] text-muted-foreground dark:text-muted-foreground">
                {message.graph!.anchors?.length ?? 0} entities ·{" "}
                {message.graph!.triples?.length ?? 0} relations
              </span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
});

export default MessageBubble;
