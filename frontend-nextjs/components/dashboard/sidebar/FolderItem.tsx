"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Document } from "@/types";
import DocumentItem from "./DocumentItem";
import { getErrorMessage } from "@/lib/utils/errors";

interface FolderItemProps {
  folderName: string;
  documents: Document[];
  selectedDocs: Set<string>;
  expandedFolders: Set<string>;
  forceExpanded?: boolean;
  // A read-only "user" sees the folder and its file count, but never the
  // files themselves — the backend redacts them too, this is just the UI half.
  canSeeFiles: boolean;
  // Deleting a folder is Admin/System Owner only; the API 403s for everyone
  // else, so don't offer the button to them.
  canManageFolders: boolean;
  onToggleFolder: (folderName: string) => void;
  onToggleDoc: (docId: string) => void;
  onSelectAllFolder: (folderName: string, anySelected: boolean, docIds: string[]) => void;
  onDeleteDoc: (docId: string) => void;
  onRenameDoc: (docId: string, newFileName: string) => Promise<void>;
  onDeleteFolder: (folderName: string) => void;
  onRenameFolder: (folderName: string, newFolderName: string) => Promise<void>;
  deletingDocId: string | null;
  isDeletingFolder: boolean;
  animationDelay: number;
}

const FolderItem = React.memo(function FolderItem({
  folderName,
  documents: folderDocs,
  selectedDocs,
  expandedFolders,
  forceExpanded = false,
  canSeeFiles,
  canManageFolders,
  onToggleFolder,
  onToggleDoc,
  onSelectAllFolder,
  onDeleteDoc,
  onRenameDoc,
  onDeleteFolder,
  onRenameFolder,
  deletingDocId,
  isDeletingFolder,
  animationDelay,
}: FolderItemProps) {
  // While searching, matched folders are force-expanded so hits are visible.
  const isExpanded =
    canSeeFiles && (forceExpanded || expandedFolders.has(folderName));
  const folderDocCount = folderDocs.length;

  // Inline folder rename (Admin/System Owner only). Mirrors DocumentItem's
  // editor. Not optimistic — the folder name is this row's key, so the editor
  // must stay mounted through the request; see useRenameFolder.
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(folderName);
  const [renaming, setRenaming] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const startRename = useCallback(
    (e?: React.MouseEvent) => {
      e?.stopPropagation();
      if (isDeletingFolder || renaming) return;
      setDraft(folderName);
      setRenameError(null);
      setIsEditing(true);
    },
    [folderName, isDeletingFolder, renaming]
  );

  const cancelRename = useCallback(() => {
    setIsEditing(false);
    setRenameError(null);
  }, []);

  const commitRename = useCallback(async () => {
    const next = draft.trim();
    if (!next || next === folderName) {
      cancelRename();
      return;
    }
    setRenaming(true);
    setRenameError(null);
    try {
      await onRenameFolder(folderName, next);
      setIsEditing(false);
    } catch (err: any) {
      setRenameError(getErrorMessage(err, "Rename failed. Please try again."));
    } finally {
      setRenaming(false);
    }
  }, [draft, folderName, onRenameFolder, cancelRename]);

  useEffect(() => {
    if (!isEditing) return;
    const input = inputRef.current;
    if (!input) return;
    input.focus();
    input.select();
  }, [isEditing]);

  if (folderDocCount === 0) return null;

  const folderDocIds = folderDocs.map((d) => d.id);
  const anyFolderDocsSelected = folderDocIds.some((id) => selectedDocs.has(id));

  return (
    <div
      className={`data-load ${isDeletingFolder ? "opacity-60 pointer-events-none" : ""}`}
      style={{ animationDelay: `${animationDelay}ms` }}
    >
      {/* Folder Header */}
      <div className="group rounded-lg transition-colors hover:bg-surface-2 dark:hover:bg-accent/60">
        <div className="flex items-center gap-2 px-2 py-2">
          {canSeeFiles ? (
            <button
              onClick={() => onToggleFolder(folderName)}
              disabled={isDeletingFolder}
              className="text-muted-foreground hover:text-foreground dark:hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
            >
              <motion.svg
                className="w-3.5 h-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                animate={{ rotate: isExpanded ? 90 : 0 }}
                transition={{ duration: 0.15, ease: "easeInOut" }}
              >
                <path d="M9 5l7 7-7 7" />
              </motion.svg>
            </button>
          ) : (
            // Keep the row aligned with expandable folders above/below it.
            <span className="w-3.5 flex-shrink-0" aria-hidden="true" />
          )}

          <input
            type="checkbox"
            checked={anyFolderDocsSelected}
            disabled={isDeletingFolder}
            onChange={() => onSelectAllFolder(folderName, anyFolderDocsSelected, folderDocIds)}
            className="tactical-checkbox flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
            title={
              anyFolderDocsSelected
                ? "Deselect all in folder"
                : "Select all in folder"
            }
          />

          {isDeletingFolder ? (
            <div className="w-3.5 h-3.5 border-2 border-border border-t-border dark:border-border dark:border-t-border rounded-full animate-spin flex-shrink-0" />
          ) : (
            <svg
              className="w-4 h-4 text-muted-foreground dark:text-muted-foreground flex-shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M4 20h16a2 2 0 002-2V8a2 2 0 00-2-2h-7.93a2 2 0 01-1.66-.9l-.82-1.2A2 2 0 008.93 3H4a2 2 0 00-2 2v13c0 1.1.9 2 2 2z" />
            </svg>
          )}

          <div className="flex-1 min-w-0">
            {isEditing ? (
              <input
                ref={inputRef}
                type="text"
                value={draft}
                disabled={renaming}
                onChange={(e) => setDraft(e.target.value)}
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
                onBlur={() => {
                  if (!renaming) commitRename();
                }}
                onClick={(e) => e.stopPropagation()}
                aria-label={`Rename folder ${folderName}`}
                className="w-full px-1.5 py-0.5 rounded-md bg-surface-2 dark:bg-card border border-border text-sm font-medium text-foreground focus:outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15 transition-all disabled:opacity-60"
              />
            ) : (
              <div className="text-sm font-medium text-foreground dark:text-foreground truncate">
                {folderName}
              </div>
            )}
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
          </div>

          {!isEditing && (
            <span className="text-[11px] text-muted-foreground dark:text-muted-foreground font-mono flex-shrink-0">
              {folderDocCount}
            </span>
          )}

          {!isDeletingFolder && !isEditing && canManageFolders && (
            <button
              onClick={startRename}
              className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 text-muted-foreground hover:text-foreground dark:hover:text-white transition-all p-0.5 flex-shrink-0"
              title="Rename folder"
              aria-label={`Rename folder ${folderName}`}
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4 12.5-12.5z" />
              </svg>
            </button>
          )}

          {isEditing && (
            <button
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

          {!isDeletingFolder && !isEditing && canManageFolders && (
            <button
              onClick={() => onDeleteFolder(folderName)}
              className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-red-600 dark:hover:text-red-400 transition-all p-0.5 flex-shrink-0"
              title="Delete folder"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Folder Documents */}
      <AnimatePresence initial={false}>
        {isExpanded && folderDocs.length > 0 && (
          <motion.div
            key="folder-docs"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: "easeInOut" }}
            style={{ overflow: "hidden" }}
          >
            <div className="ml-3 pl-3 border-l border-border dark:border-border space-y-0.5">
              {folderDocs.map((doc, index) => (
                <DocumentItem
                  key={doc.id}
                  document={doc}
                  isSelected={selectedDocs.has(doc.id)}
                  onToggle={onToggleDoc}
                  onDelete={onDeleteDoc}
                  onRename={onRenameDoc}
                  isDeleting={deletingDocId === doc.id}
                  index={index}
                />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default FolderItem;
