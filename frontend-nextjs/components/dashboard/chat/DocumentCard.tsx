"use client";

/**
 * Download card for a file the agent built with build_document (PDF, Word,
 * PowerPoint, Excel). The file lives in iDrive E2; clicking asks the backend for
 * a freshly signed link, so the card keeps working after the tool's own link
 * expires. Falls back to that link if the request fails.
 */

import { useState, type MouseEvent } from "react";
import { GeneratedDocument } from "@/types";
import { chatDocumentsApi } from "@/lib/api/chatDocuments";
import { useFilePreviewStore } from "@/lib/stores/filePreviewStore";

const FORMAT_STYLE: Record<string, { label: string; className: string }> = {
  pdf: { label: "PDF", className: "bg-red-500/10 text-red-600 dark:text-red-400" },
  docx: { label: "DOCX", className: "bg-blue-500/10 text-blue-600 dark:text-blue-400" },
  pptx: { label: "PPTX", className: "bg-orange-500/10 text-orange-600 dark:text-orange-400" },
  xlsx: { label: "XLSX", className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" },
};

function formatSize(bytes?: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentCard({ doc }: { doc: GeneratedDocument }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const openPreview = useFilePreviewStore((s) => s.openPreview);
  const canPreview = !!doc.preview_key;
  const ext = (doc.format || doc.filename.split(".").pop() || "").toLowerCase();
  const style = FORMAT_STYLE[ext] || { label: ext.toUpperCase() || "FILE", className: "bg-muted text-muted-foreground" };

  const download = async (e?: MouseEvent) => {
    e?.stopPropagation();
    setBusy(true);
    setError(null);
    let url = doc.url;
    try {
      if (doc.object_key) url = await chatDocumentsApi.downloadUrl(doc.object_key);
    } catch {
      // Use the link the tool returned (valid for several days).
    }
    setBusy(false);
    if (!url) {
      setError("Download link unavailable.");
      return;
    }
    window.open(url, "_blank", "noopener,noreferrer");
  };

  return (
    <div
      className={`mt-3 max-w-md rounded-xl border border-border bg-surface-2 dark:bg-card px-4 py-3${
        canPreview ? " cursor-pointer hover:border-foreground/30 transition-colors" : ""
      }`}
      onClick={canPreview ? () => openPreview(doc) : undefined}
      role={canPreview ? "button" : undefined}
      title={canPreview ? "Open preview" : undefined}
    >
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 shrink-0 rounded-lg flex items-center justify-center text-[10px] font-semibold ${style.className}`}>
          {style.label}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-foreground truncate" title={doc.filename}>
            {doc.filename}
          </div>
          <div className="text-xs text-muted-foreground">
            {[formatSize(doc.size_bytes), doc.version && doc.version > 1 ? `version ${doc.version}` : null]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>
        {canPreview && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              openPreview(doc);
            }}
            className="px-3 py-1.5 rounded-lg border border-border text-foreground text-xs font-medium hover:bg-secondary dark:hover:bg-accent transition-colors"
          >
            Preview
          </button>
        )}
        <button
          onClick={download}
          disabled={busy}
          className="px-3 py-1.5 rounded-lg bg-brand text-brand-foreground text-xs font-medium hover:bg-brand-hover disabled:opacity-50 transition-colors"
        >
          {busy ? "Opening…" : "Download"}
        </button>
      </div>
      {error && <div className="mt-2 text-[11px] text-red-500">{error}</div>}
    </div>
  );
}
