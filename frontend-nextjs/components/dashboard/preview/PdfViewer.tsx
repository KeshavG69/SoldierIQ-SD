"use client";

/**
 * Renders a PDF page by page with react-pdf (port of enterprise's pdf-driver).
 * The bytes come from the authenticated backend preview endpoint, so no bucket
 * CORS rules are needed. The pdf.js worker is bundled (no CDN), so previews also
 * work on networks without internet access.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const MAX_RENDER_WIDTH = 1200;
const HORIZONTAL_PADDING_PX = 32;
const RESIZE_DEBOUNCE_MS = 120;

export default function PdfViewer({ load }: { load: () => Promise<ArrayBuffer> }) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [buffer, setBuffer] = useState<ArrayBuffer | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pageWidth, setPageWidth] = useState(0);
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");
  const [errorDetail, setErrorDetail] = useState("");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setErrorDetail("");
    setBuffer(null);
    setNumPages(0);
    load()
      .then((buf) => {
        if (!cancelled) setBuffer(buf);
      })
      .catch((err) => {
        if (cancelled) return;
        setErrorDetail(err?.response?.status ? `HTTP ${err.response.status}` : err?.message ?? String(err));
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  // Fit pages to the pane width, re-measured when the pane is resized.
  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const apply = () => {
      const w = Math.min(MAX_RENDER_WIDTH, Math.max(0, el.clientWidth - HORIZONTAL_PADDING_PX));
      if (w > 0) setPageWidth(w);
    };
    apply();
    let timeout: number | null = null;
    const ro = new ResizeObserver(() => {
      if (timeout) window.clearTimeout(timeout);
      timeout = window.setTimeout(apply, RESIZE_DEBOUNCE_MS);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      if (timeout) window.clearTimeout(timeout);
    };
  }, []);

  // A stable `file` prop, so react-pdf doesn't reload on every render.
  const file = useMemo(() => (buffer ? { data: new Uint8Array(buffer) } : null), [buffer]);

  return (
    <div className="relative h-full w-full bg-surface-2 dark:bg-background">
      {status === "loading" && (
        <div className="absolute inset-0 z-10 flex items-center justify-center gap-2 text-[13px] text-muted-foreground">
          <div className="w-4 h-4 border-2 border-border border-t-foreground rounded-full animate-spin" />
          <span>Loading document…</span>
        </div>
      )}
      {status === "error" && (
        <div className="absolute inset-0 z-10 flex items-center justify-center p-6">
          <div className="max-w-sm text-center space-y-1">
            <p className="text-[13px] font-medium text-foreground">Preview unavailable</p>
            <p className="text-[12px] text-muted-foreground">Use Download to open the file.</p>
            {errorDetail && <p className="text-[11px] text-muted-foreground break-all">{errorDetail}</p>}
          </div>
        </div>
      )}
      <div ref={wrapperRef} className="h-full w-full overflow-y-auto overflow-x-hidden flex flex-col items-center py-4">
        {file && pageWidth > 0 && (
          <Document
            file={file}
            onLoadSuccess={({ numPages: n }) => {
              setNumPages(n);
              setStatus("loaded");
            }}
            onLoadError={(err) => {
              setErrorDetail(err.message);
              setStatus("error");
            }}
            loading=""
            error=""
            className="flex flex-col items-center gap-4"
          >
            {Array.from({ length: numPages }, (_, i) => (
              <Page
                key={i}
                pageNumber={i + 1}
                width={pageWidth}
                renderAnnotationLayer={false}
                renderTextLayer
                className="shadow-md bg-white"
              />
            ))}
          </Document>
        )}
      </div>
    </div>
  );
}
