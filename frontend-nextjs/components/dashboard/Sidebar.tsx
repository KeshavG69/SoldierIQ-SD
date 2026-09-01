"use client";

import { useState, useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/lib/stores/authStore";
import { useDocumentStore } from "@/lib/stores/documentStore";
import { useDocuments, useKnowledgeBases, documentKeys } from "@/lib/hooks/useDocuments";
import { useUploadDocument } from "@/lib/hooks/useUploadDocument";
import { useDeleteDocument, useDeleteKnowledgeBase } from "@/lib/hooks/useDeleteDocument";
import { useRenameDocument } from "@/lib/hooks/useRenameDocument";
import SidebarHeader from "./sidebar/SidebarHeader";
import FolderTree from "./sidebar/FolderTree";
import UploadModal from "./sidebar/UploadModal";
import DriveImportBanner from "./sidebar/DriveImportBanner";

export default function Sidebar() {
  const user = useAuthStore((s) => s.user);
  // Admins and System Owners manage the knowledge base; a plain "user" member
  // is read-only and doesn't see individual files at all. The API enforces both
  // halves (it redacts the file rows and rejects writes) — this keeps the UI
  // from offering what the server will refuse.
  const isUploader = user?.role === "admin" || user?.role === "system_owner";
  const queryClient = useQueryClient();

  // Server state via React Query (cached, deduped)
  const { data: documents = [], isLoading } = useDocuments(user?.organization_id);
  const { data: knowledgeBases = [] } = useKnowledgeBases(user?.organization_id);

  // Mutations
  const uploadMutation = useUploadDocument();
  const deleteMutation = useDeleteDocument();
  const deleteKBMutation = useDeleteKnowledgeBase();
  // Destructured because `mutateAsync` keeps a stable identity across renders
  // while the mutation object does not — handing the object's method straight
  // to the tree would re-render every memoized DocumentItem on each render.
  const { mutateAsync: renameDocument } = useRenameDocument();

  // Client-side selection state (stays in Zustand)
  const {
    selectedDocs,
    uploadStatus,
    deletingKB,
    toggleDocSelection,
    selectAllDocs,
    deselectAllDocs,
    selectDocs,
    deselectDocs,
    uploadDocuments,
    uploadYouTubeVideo,
  } = useDocumentStore();

  const [showUploadModal, setShowUploadModal] = useState(false);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  // In-app delete confirmation (replaces window.confirm, which browsers can
  // silently suppress — the cause of "delete does nothing").
  const [pendingDelete, setPendingDelete] = useState<
    { kind: "doc" | "folder"; id: string; label: string } | null
  >(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const totalDocs = Array.isArray(documents) ? documents.length : 0;

  // Count only selections that still correspond to an existing document. The
  // persisted selection set can otherwise carry stale IDs (deleted docs, or an
  // older cached doc list), which would show a "selected" count higher than the
  // number of documents.
  const validSelectedCount = useMemo(
    () =>
      Array.isArray(documents)
        ? documents.filter((d) => selectedDocs.has(d.id)).length
        : 0,
    [documents, selectedDocs]
  );

  const folderList = useMemo(() => {
    const allFolders = new Set<string>();
    (Array.isArray(knowledgeBases) ? knowledgeBases : []).forEach((kb) =>
      allFolders.add(kb.name)
    );
    (Array.isArray(documents) ? documents : []).forEach((doc) => {
      const folder = doc.folder_name || "Uncategorized";
      allFolders.add(folder);
    });
    return Array.from(allFolders).sort();
  }, [knowledgeBases, documents]);

  const handleUploadClick = useCallback(() => {
    setShowUploadModal(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setShowUploadModal(false);
  }, []);

  // uploadDocuments/uploadYouTubeVideo live in the Zustand store and update
  // ITS OWN state, but the sidebar actually renders from React Query
  // (useDocuments/useKnowledgeBases above). Without this invalidation the
  // new folder/doc only exists in Zustand's shadow copy — the visible list
  // never learns about it until something else (e.g. a full reload)
  // happens to remount the query. Invalidating here is what makes the
  // upload show up on its own, and it also seeds useDocuments' cache with a
  // "processing" doc so its 5s poll picks up and shows live status changes.
  const invalidateDocumentQueries = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: documentKeys.list(user?.organization_id) });
    queryClient.invalidateQueries({ queryKey: documentKeys.knowledgeBases(user?.organization_id) });
  }, [queryClient, user?.organization_id]);

  const handleUpload = useCallback(
    async (files: File[], folderName: string) => {
      setExpandedFolders((prev) => {
        const next = new Set(prev);
        next.add(folderName);
        return next;
      });
      try {
        await uploadDocuments(files, folderName);
      } finally {
        invalidateDocumentQueries();
      }
    },
    [uploadDocuments, invalidateDocumentQueries]
  );

  const handleYouTubeUpload = useCallback(
    async (url: string, folderName: string) => {
      setExpandedFolders((prev) => {
        const next = new Set(prev);
        next.add(folderName);
        return next;
      });
      try {
        await uploadYouTubeVideo(url, folderName);
      } finally {
        invalidateDocumentQueries();
      }
    },
    [uploadYouTubeVideo, invalidateDocumentQueries]
  );

  const handleToggleFolder = useCallback((folderName: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(folderName)) {
        next.delete(folderName);
      } else {
        next.add(folderName);
      }
      return next;
    });
  }, []);

  const handleSelectAllFolder = useCallback(
    (_folderName: string, anySelected: boolean, docIds: string[]) => {
      if (anySelected) {
        deselectDocs(docIds);
      } else {
        selectDocs(docIds);
      }
    },
    [selectDocs, deselectDocs]
  );

  // Delete buttons just open the confirmation; the actual work happens in
  // confirmDelete once the user confirms in-app.
  const handleDeleteDoc = useCallback(
    (docId: string) => {
      const doc = documents.find((d) => d.id === docId);
      setDeleteError(null);
      setPendingDelete({ kind: "doc", id: docId, label: doc?.file_name || "this document" });
    },
    [documents]
  );

  // Renaming is inline in the row — no confirmation needed. Errors bubble
  // back to DocumentItem, which keeps the editor open and shows the message.
  const handleRenameDoc = useCallback(
    async (docId: string, newFileName: string) => {
      await renameDocument({
        docId,
        newFileName,
        organizationId: user?.organization_id || "",
      });
    },
    [renameDocument, user?.organization_id]
  );

  const handleDeleteFolder = useCallback((folderName: string) => {
    setDeleteError(null);
    setPendingDelete({ kind: "folder", id: folderName, label: folderName });
  }, []);

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const orgId = user?.organization_id || "";
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      if (pendingDelete.kind === "doc") {
        setDeletingDocId(pendingDelete.id);
        await deleteMutation.mutateAsync({ docId: pendingDelete.id, organizationId: orgId });
      } else {
        await deleteKBMutation.mutateAsync({ folderName: pendingDelete.id, organizationId: orgId });
        setExpandedFolders((prev) => {
          const next = new Set(prev);
          next.delete(pendingDelete.id);
          return next;
        });
      }
      setPendingDelete(null);
    } catch (e: any) {
      setDeleteError(
        e?.response?.data?.detail || e?.message || "Delete failed. Please try again."
      );
    } finally {
      setDeletingDocId(null);
      setDeleteBusy(false);
    }
  }, [pendingDelete, deleteMutation, deleteKBMutation, user?.organization_id]);

  return (
    <div className="flex-1 bg-surface-2 border-r border-border flex flex-col relative">
      <SidebarHeader
        totalDocs={totalDocs}
        selectedCount={validSelectedCount}
        onSelectAll={selectAllDocs}
        onClearSelection={deselectAllDocs}
        onUploadClick={handleUploadClick}
        uploadStatus={uploadStatus}
      />

      {/* Live progress for a Google Drive folder import */}
      <DriveImportBanner documents={documents} />

      <div className="flex-1 overflow-y-auto tactical-scrollbar p-4">
        <FolderTree
          documents={documents}
          knowledgeBases={knowledgeBases}
          selectedDocs={selectedDocs}
          expandedFolders={expandedFolders}
          onToggleFolder={handleToggleFolder}
          onToggleDoc={toggleDocSelection}
          onSelectAllFolder={handleSelectAllFolder}
          onDeleteDoc={handleDeleteDoc}
          onRenameDoc={handleRenameDoc}
          canSeeFiles={isUploader}
          canManageFolders={isUploader}
          onDeleteFolder={handleDeleteFolder}
          deletingDocId={deletingDocId}
          deletingKB={deletingKB}
          isLoading={isLoading}
        />
      </div>

      <UploadModal
        isOpen={showUploadModal}
        onClose={handleCloseModal}
        folders={folderList}
        onUpload={handleUpload}
        onYouTubeUpload={handleYouTubeUpload}
        uploadStatus={uploadStatus}
      />

      {/* Delete confirmation (in-app, not window.confirm) */}
      {pendingDelete && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[60] flex items-center justify-center px-4">
          <div className="w-full max-w-sm rounded-2xl bg-card border border-border shadow-2xl overflow-hidden">
            <div className="px-6 py-4 border-b border-border">
              <h3 className="text-base font-semibold text-foreground">
                {pendingDelete.kind === "doc" ? "Delete document" : "Delete knowledge base"}
              </h3>
            </div>
            <div className="px-6 py-4">
              <p className="text-sm text-muted-foreground">
                {pendingDelete.kind === "doc" ? (
                  <>
                    Delete <span className="font-medium text-foreground">{pendingDelete.label}</span>? This can’t be undone.
                  </>
                ) : (
                  <>
                    Delete <span className="font-medium text-foreground">{pendingDelete.label}</span> and all documents in it? This can’t be undone.
                  </>
                )}
              </p>
              {deleteError && <p className="text-xs text-red-500 mt-2">{deleteError}</p>}
            </div>
            <div className="px-6 py-4 border-t border-border flex justify-end gap-2 bg-surface-2 dark:bg-card/40">
              <button
                onClick={() => {
                  setPendingDelete(null);
                  setDeleteError(null);
                }}
                disabled={deleteBusy}
                className="px-4 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:bg-secondary dark:hover:bg-accent transition-colors disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleteBusy}
                className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-colors disabled:opacity-60 inline-flex items-center gap-2"
              >
                {deleteBusy && (
                  <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                )}
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
