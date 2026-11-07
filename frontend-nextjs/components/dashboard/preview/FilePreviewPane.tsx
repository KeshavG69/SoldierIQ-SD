"use client";

/**
 * Side pane that previews a file the agent built (port of enterprise's
 * FilePreviewSidebarContent): back to chat, file icon + title, download, and
 * expand to full width. Every format is shown as the PDF rendering the backend
 * made when the file was built (docx/pptx/xlsx are converted with LibreOffice
 * in the document sandbox), so the pane only needs one viewer.
 */

import dynamic from "next/dynamic";
import { useCallback, useState } from "react";
import { ArrowLeft, Download, Maximize2, Minimize2 } from "lucide-react";
import apiClient from "@/lib/api/client";
import { chatDocumentsApi } from "@/lib/api/chatDocuments";
import { useFilePreviewStore } from "@/lib/stores/filePreviewStore";

const PdfViewer = dynamic(() => import("./PdfViewer"), { ssr: false });

const FORMAT_STYLE: Record<string, { label: string; className: string }> = {
  pdf: { label: "PDF", className: "bg-red-500/10 text-red-600 dark:text-red-400" },
  docx: { label: "DOC", className: "bg-blue-500/10 text-blue-600 dark:text-blue-400" },
  pptx: { label: "PPT", className: "bg-orange-500/10 text-orange-600 dark:text-orange-400" },
  xlsx: { label: "XLS", className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" },
};

export default function FilePreviewPane() {
  const doc = useFilePreviewStore((s) => s.doc);
  const isExpanded = useFilePreviewStore((s) => s.isExpanded);
  const closePreview = useFilePreviewStore((s) => s.closePreview);
  const toggleExpanded = useFilePreviewStore((s) => s.toggleExpanded);
  const [downloading, setDownloading] = useState(false);

  const previewKey = doc?.preview_key;
  const load = useCallback(async () => {
    if (!previewKey) throw new Error("No preview was rendered for this file.");
    const res = await apiClient.get<ArrayBuffer>("/chat/documents/preview", {
      params: { key: previewKey },
      responseType: "arraybuffer",
    });
    return res.data;
  }, [previewKey]);

  if (!doc) return null;

  const ext = (doc.format || doc.filename.split(".").pop() || "").toLowerCase();
  const style = FORMAT_STYLE[ext] || { label: ext.toUpperCase() || "FILE", className: "bg-muted text-muted-foreground" };
  const title = doc.filename.replace(/\.[^.]+$/, "") || doc.filename;

  const download = async () => {
    setDownloading(true);
    let url = doc.url;
    try {
      if (doc.object_key) url = await chatDocumentsApi.downloadUrl(doc.object_key);
    } catch {
      // fall back to the tool's own (multi-day) link
    }
    setDownloading(false);
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  };

  const iconButton =
    "h-7 w-7 shrink-0 inline-flex items-center justify-center rounded-md border border-border bg-background hover:bg-secondary dark:hover:bg-accent text-foreground transition-colors disabled:opacity-50";

  return (
    <div className="flex h-full w-full flex-col bg-background border-l border-border">
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <button type="button" onClick={closePreview} className={iconButton} aria-label="Back to chat" title="Back to chat">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className={`h-7 min-w-7 px-1 rounded-md flex items-center justify-center text-[9px] font-semibold ${style.className}`}>
          {style.label}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-medium text-foreground truncate" title={doc.filename}>
            {title}
          </div>
          {doc.version && doc.version > 1 ? (
            <div className="text-[11px] text-muted-foreground">version {doc.version}</div>
          ) : null}
        </div>
        <button type="button" onClick={download} disabled={downloading} className={iconButton} aria-label="Download" title="Download">
          <Download className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={toggleExpanded}
          className={`${iconButton} hidden md:inline-flex`}
          aria-label={isExpanded ? "Collapse preview" : "Expand preview"}
          title={isExpanded ? "Collapse" : "Expand"}
        >
          {isExpanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">
        {/* key: a fresh viewer per document/version, so pages never mix */}
        <PdfViewer key={`${doc.slug}:${doc.version ?? 1}:${previewKey ?? ""}`} load={load} />
      </div>
    </div>
  );
}
