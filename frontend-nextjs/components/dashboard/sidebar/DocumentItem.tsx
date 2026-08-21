"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Document } from "@/types";
import { documentsApi } from "@/lib/api/documents";
import IngestionPipeline from "./IngestionPipeline";

interface DocumentItemProps {
  document: Document;
  isSelected: boolean;
  onToggle: (docId: string) => void;
  onDelete: (docId: string) => void;
  // Resolves once the new name is persisted; rejects with a message to show
  // inline if the backend refuses it.
  onRename: (docId: string, newFileName: string) => Promise<void>;
  isDeleting: boolean;
  index?: number;
}

const DocumentItem = React.memo(function DocumentItem({
  document: doc,
  isSelected,
  onToggle,
  onDelete,
  onRename,
  isDeleting,
  index = 0,
}: DocumentItemProps) {
  const isFailed = doc.status === "failed";
  const [opening, setOpening] = useState(false);

  // Inline rename. `draft` is only meaningful while editing; it is re-seeded
  // from the document every time editing starts, so an external update to the
  // name never gets clobbered by a stale draft.
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(doc.file_name);
  const [renaming, setRenaming] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const canRename = !isDeleting && !renaming;

  const startRename = useCallback(
    (e?: React.MouseEvent) => {
      e?.stopPropagation();
      if (!canRename) return;
      setDraft(doc.file_name);
      setRenameError(null);
      setIsEditing(true);
    },
    [canRename, doc.file_name]
  );

  const cancelRename = useCallback(() => {
    setIsEditing(false);
    setRenameError(null);
  }, []);

  const commitRename = useCallback(async () => {
    const next = draft.trim();
    // Nothing typed, or nothing changed — just close the editor.
    if (!next || next === doc.file_name) {
      cancelRename();
      return;
    }
    setRenaming(true);
    setRenameError(null);
    try {
      await onRename(doc.id, next);
      setIsEditing(false);
    } catch (err: any) {
      setRenameError(
        err?.response?.data?.detail || err?.message || "Rename failed. Please try again."
      );
      // Stay in edit mode so the typed name isn't lost.
    } finally {
      setRenaming(false);
    }
  }, [draft, doc.file_name, doc.id, onRename, cancelRename]);

  // Focus the input when editing opens, and preselect the name without its
  // extension — that's the part people actually retype.
  useEffect(() => {
    if (!isEditing) return;
    const input = inputRef.current;
    if (!input) return;
    input.focus();
    const dot = input.value.lastIndexOf(".");
    input.setSelectionRange(0, dot > 0 ? dot : input.value.length);
  }, [isEditing]);

  // A failed save re-enables the input, but disabling it dropped focus — put
  // it back (without reselecting) so the user can fix the name and retry.
  useEffect(() => {
    if (!renaming && isEditing && renameError) inputRef.current?.focus();
  }, [renaming, isEditing, renameError]);

  // A downloadable file exists when the doc finished and has a file_key. We do
  // NOT have a URL yet — fetch a fresh presigned one only on click, so the list
  // endpoint never has to mint URLs for every doc on every poll.
  const canOpen = doc.status === "completed" && !!doc.file_key && !isDeleting;

  const handleOpen = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      if (!canOpen || opening) return;
      setOpening(true);
      // Open a blank tab synchronously (inside the click) so the popup blocker
      // doesn't kill it; we set its location once the URL comes back.
      const win = window.open("", "_blank");
      try {
        const fresh = await documentsApi.getDocument(doc.id);
        if (fresh.file_url) {
          if (win) win.location.href = fresh.file_url;
          else window.open(fresh.file_url, "_blank", "noopener,noreferrer");
        } else if (win) {
          win.close();
        }
      } catch {
        if (win) win.close();
      } finally {
        setOpening(false);
      }
    },
    [canOpen, opening, doc.id]
  );

  return (
    <>
    <motion.div
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.02 }}
      className={`group relative rounded-lg transition-colors ${
        isDeleting
          ? "opacity-60"
          : isFailed
            ? "opacity-60"
            : isSelected
              ? "bg-secondary dark:bg-card"
              : "hover:bg-surface-2 dark:hover:bg-accent/60"
      }`}
    >
      <div className="flex items-start gap-2 px-2 py-1.5">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => onToggle(doc.id)}
          className="tactical-checkbox mt-0.5 flex-shrink-0"
          disabled={doc.status === "processing" || isFailed || isDeleting}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2">
            {/*
              Filename is clickable when the doc finished and has a file. We
              fetch a FRESH presigned URL on click (not pre-generated for the
              whole list) and open it in a new tab. stopPropagation so the click
              doesn't toggle the row's selection state.
            */}
            {isEditing ? (
              <input
                ref={inputRef}
                type="text"
                value={draft}
                disabled={renaming}
                onChange={(e) => setDraft(e.target.value)}
                // Keys are handled here (not on a form) so Enter/Escape never
                // reach the sidebar's other handlers.
                onKeyDown={(e) => {
                  e.stopPropagation();
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitRename();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    cancelRename();
                  }
                }}
                // Clicking away commits, the same as Enter. The Cancel button
                // suppresses this by preventing the mousedown that would blur.
                onBlur={() => {
                  if (!renaming) commitRename();
                }}
                onClick={(e) => e.stopPropagation()}
                aria-label={`Rename ${doc.file_name}`}
                className="flex-1 min-w-0 px-1.5 py-0.5 rounded-md bg-surface-2 dark:bg-card border border-border text-xs text-foreground focus:outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15 transition-all disabled:opacity-60"
              />
            ) : canOpen ? (
              <button
                type="button"
                onClick={handleOpen}
                disabled={opening}
                className="text-left text-xs text-foreground dark:text-foreground break-words flex-1 leading-tight cursor-pointer hover:text-foreground dark:hover:text-foreground hover:underline underline-offset-2 decoration-muted-foreground dark:decoration-muted-foreground disabled:opacity-60"
                title="Open file in a new tab"
              >
                {doc.file_name}
                {opening && " …"}
              </button>
            ) : (
              <div className="text-xs text-foreground dark:text-foreground break-words flex-1 leading-tight">
                {doc.file_name}
              </div>
            )}
            {isDeleting && (
              <div className="w-3 h-3 border-2 border-red-300 border-t-red-600 rounded-full animate-spin flex-shrink-0 mt-0.5" />
            )}
            {!isDeleting && doc.status === "processing" && (
              <div className="w-3 h-3 border-2 border-border border-t-border dark:border-border dark:border-t-border rounded-full animate-spin flex-shrink-0 mt-0.5" />
            )}
          </div>
          {isEditing && !renameError && (
            <div className="text-[10px] text-muted-foreground mt-0.5">
              {renaming ? "Saving…" : "Enter to save · Esc to cancel"}
            </div>
          )}
          {renameError && (
            <div className="text-[10px] text-red-500 dark:text-red-400 mt-0.5">
              {renameError}
            </div>
          )}
          {isDeleting && (
            <div className="text-[10px] text-red-600 dark:text-red-400 mt-0.5">
              Deleting…
            </div>
          )}
          {!isDeleting && doc.status === "processing" && (
            <IngestionPipeline document={doc} />
          )}
          {!isDeleting && doc.status === "failed" && doc.error && (
            <div className="text-[10px] text-red-500 dark:text-red-400 mt-0.5 truncate">
              {doc.error}
            </div>
          )}
          {!isDeleting && (!doc.status || doc.status === "completed") && doc.created_at && (
            <div className="text-[10px] text-muted-foreground mt-0.5">
              {new Date(doc.created_at).toLocaleDateString("en-US", {
                year: "numeric",
                month: "short",
                day: "numeric",
              })}
            </div>
          )}
        </div>
        {!isDeleting && !isEditing && (
          <button
            onClick={startRename}
            className="text-muted-foreground hover:text-foreground dark:hover:text-white transition-all p-0.5 flex-shrink-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
            title="Rename file"
            aria-label={`Rename ${doc.file_name}`}
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4 12.5-12.5z" />
            </svg>
          </button>
        )}
        {isEditing && (
          <button
            // mouseDown (not click) so the cancel wins the race with the
            // input's blur-commits handler.
            onMouseDown={(e) => {
              e.preventDefault();
              cancelRename();
            }}
            disabled={renaming}
            className="text-muted-foreground hover:text-foreground dark:hover:text-white transition-all p-0.5 flex-shrink-0 disabled:opacity-50"
            title="Cancel rename"
            aria-label="Cancel rename"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
        {!isDeleting && !isEditing && (
          <button
            onClick={() => onDelete(doc.id)}
            className={`text-muted-foreground hover:text-red-600 dark:hover:text-red-400 transition-all p-0.5 flex-shrink-0 ${
              isFailed ? "opacity-100" : "opacity-0 group-hover:opacity-100"
            }`}
            title="Delete document"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
            </svg>
          </button>
        )}
      </div>
    </motion.div>
    </>
  );
});

export default DocumentItem;
