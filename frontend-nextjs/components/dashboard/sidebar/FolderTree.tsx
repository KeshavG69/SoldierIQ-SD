"use client";

import React, { useMemo, useState } from "react";
import { Document, KnowledgeBase } from "@/types";
import FolderItem from "./FolderItem";

interface FolderTreeProps {
  documents: Document[];
  knowledgeBases: KnowledgeBase[];
  selectedDocs: Set<string>;
  expandedFolders: Set<string>;
  onToggleFolder: (folderName: string) => void;
  onToggleDoc: (docId: string) => void;
  onSelectAllFolder: (folderName: string, anySelected: boolean, docIds: string[]) => void;
  onDeleteDoc: (docId: string) => void;
  onDeleteFolder: (folderName: string) => void;
  deletingDocId: string | null;
  deletingKB: string | null;
  isLoading: boolean;
}

const FolderTree = React.memo(function FolderTree({
  documents,
  knowledgeBases,
  selectedDocs,
  expandedFolders,
  onToggleFolder,
  onToggleDoc,
  onSelectAllFolder,
  onDeleteDoc,
  onDeleteFolder,
  deletingDocId,
  deletingKB,
  isLoading,
}: FolderTreeProps) {
  const documentsByFolder = useMemo(() => {
    return (Array.isArray(documents) ? documents : []).reduce(
      (acc, doc) => {
        const folder = doc.folder_name || "Uncategorized";
        if (!acc[folder]) {
          acc[folder] = [];
        }
        acc[folder].push(doc);
        return acc;
      },
      {} as Record<string, Document[]>
    );
  }, [documents]);

  const folderList = useMemo(() => {
    const allFolders = new Set<string>();
    (Array.isArray(knowledgeBases) ? knowledgeBases : []).forEach((kb) => {
      // A KB can arrive with a missing/blank name — skip it so it never
      // becomes an `undefined` entry that later crashes name comparisons.
      if (kb?.name) allFolders.add(kb.name);
    });
    Object.keys(documentsByFolder).forEach((folder) =>
      allFolders.add(folder)
    );
    return Array.from(allFolders).sort();
  }, [knowledgeBases, documentsByFolder]);

  const [query, setQuery] = useState("");
  const isSearching = query.trim().length > 0;

  // Each entry is a folder + the documents to show under it. Searching matches
  // folder names AND file names: a folder-name hit shows all its docs; a
  // file-name hit shows just the matching files (and the folder auto-expands).
  const filteredFolders = useMemo(() => {
    const q = query.trim().toLowerCase();
    const entryFor = (folderName: string, docs: Document[]) => ({ folderName, docs });

    if (!q) {
      return folderList.map((name) => entryFor(name, documentsByFolder[name] || []));
    }

    const out: { folderName: string; docs: Document[] }[] = [];
    for (const folderName of folderList) {
      const docs = documentsByFolder[folderName] || [];
      if ((folderName || "").toLowerCase().includes(q)) {
        out.push(entryFor(folderName, docs));
      } else {
        const matching = docs.filter((d) =>
          (d.file_name || "").toLowerCase().includes(q)
        );
        if (matching.length > 0) out.push(entryFor(folderName, matching));
      }
    }
    return out;
  }, [folderList, documentsByFolder, query]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <div className="w-5 h-5 border-2 border-border border-t-border dark:border-border dark:border-t-border rounded-full animate-spin mb-3" />
        <div className="text-muted-foreground text-xs">Loading</div>
      </div>
    );
  }

  if (folderList.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center px-4">
        <div className="w-10 h-10 rounded-full bg-secondary dark:bg-card flex items-center justify-center mb-3">
          <svg
            className="w-5 h-5 text-muted-foreground dark:text-muted-foreground"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <path d="M14 2v6h6" />
          </svg>
        </div>
        <div className="text-sm font-medium text-foreground dark:text-foreground mb-1">
          No documents yet
        </div>
        <div className="text-xs text-muted-foreground dark:text-muted-foreground leading-relaxed max-w-[220px]">
          Upload a document to create your first knowledge base.
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Search folders by name */}
      <div className="relative mb-3">
        <svg
          className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search folders & files…"
          className="w-full pl-8 pr-8 py-1.5 rounded-lg bg-surface-2 dark:bg-card border border-border text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15 transition-all"
        />
        {query && (
          <button
            onClick={() => setQuery("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Clear search"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {filteredFolders.length === 0 ? (
        <div className="py-8 text-center text-xs text-muted-foreground">
          Nothing matches “{query.trim()}”
        </div>
      ) : (
        <div className="space-y-1">
          {filteredFolders.map(({ folderName, docs }, folderIdx) => (
            <FolderItem
              key={folderName}
              folderName={folderName}
              documents={docs}
              selectedDocs={selectedDocs}
              expandedFolders={expandedFolders}
              forceExpanded={isSearching}
              onToggleFolder={onToggleFolder}
              onToggleDoc={onToggleDoc}
              onSelectAllFolder={onSelectAllFolder}
              onDeleteDoc={onDeleteDoc}
              onDeleteFolder={onDeleteFolder}
              deletingDocId={deletingDocId}
              isDeletingFolder={deletingKB === folderName}
              animationDelay={folderIdx * 30}
            />
          ))}
        </div>
      )}
    </div>
  );
});

export default FolderTree;
