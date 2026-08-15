"use client";

import React, { useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChatMessage } from "@/types";
import { DocumentSource } from "@/lib/stores/chatStore";
import MessageBubble from "./MessageBubble";

interface MessageListProps {
  messages: ChatMessage[];
  sourceUrls: Map<string, string>;
  onCitationHover: (
    index: number,
    messageId: string,
    x: number,
    y: number
  ) => void;
  onCitationLeave: () => void;
  onCitationClick: (source: DocumentSource, url: string | undefined) => void;
  onOpenGraph?: (message: ChatMessage) => void;
}

const MessageList = React.memo(function MessageList({
  messages,
  sourceUrls,
  onCitationHover,
  onCitationLeave,
  onCitationClick,
  onOpenGraph,
}: MessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <AnimatePresence initial={false}>
        {messages.map((message, idx) => (
          <motion.div
            key={message.id}
            layout
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
          >
            <MessageBubble
              message={message}
              sourceUrls={sourceUrls}
              animationDelay={idx * 50}
              onCitationHover={onCitationHover}
              onCitationLeave={onCitationLeave}
              onCitationClick={onCitationClick}
              onOpenGraph={onOpenGraph}
            />
          </motion.div>
        ))}
      </AnimatePresence>
      <div ref={messagesEndRef} />
    </div>
  );
});

export default MessageList;
