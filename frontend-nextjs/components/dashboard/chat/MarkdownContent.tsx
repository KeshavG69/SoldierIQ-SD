"use client";

import React, { useRef, useState, useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { exportTableToExcel, exportTableToCSV } from "@/lib/chat/exportTable";
import { ChatMessage } from "@/types";
import { DocumentSource } from "@/lib/stores/chatStore";

// Shared markdown renderer for assistant answers. Used by both the finished
// message and the streaming view so rendering stays identical. Styled with
// SoldierIQ's olive-drab prose tokens.

export const PROSE_CLASSES = `prose dark:prose-invert max-w-none font-sans
  text-[15px] leading-[1.75]
  prose-headings:font-semibold prose-headings:tracking-tight prose-headings:leading-tight
  prose-headings:text-foreground dark:prose-headings:text-foreground
  prose-h1:text-2xl prose-h1:mb-6 prose-h1:mt-10
  prose-h2:text-xl prose-h2:mb-5 prose-h2:mt-8
  prose-h3:text-lg prose-h3:mb-4 prose-h3:mt-7
  prose-h4:text-base prose-h4:mb-3 prose-h4:mt-6
  prose-p:mb-5 prose-p:leading-[1.75]
  prose-p:text-muted-foreground dark:prose-p:text-foreground
  prose-ul:my-5 prose-ul:space-y-2
  prose-ol:my-5 prose-ol:space-y-2
  prose-li:text-muted-foreground dark:prose-li:text-foreground prose-li:my-1
  prose-blockquote:border-l-2 prose-blockquote:border-border dark:prose-blockquote:border-border
  prose-blockquote:pl-4 prose-blockquote:my-5 prose-blockquote:text-muted-foreground dark:prose-blockquote:text-muted-foreground prose-blockquote:italic prose-blockquote:not-italic
  prose-a:text-foreground dark:prose-a:text-foreground prose-a:underline prose-a:underline-offset-4
  prose-strong:text-foreground dark:prose-strong:text-foreground prose-strong:font-semibold
  prose-em:text-muted-foreground dark:prose-em:text-foreground
  prose-code:text-foreground dark:prose-code:text-foreground
  prose-code:bg-secondary dark:prose-code:bg-card
  prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-[13px] prose-code:font-mono
  prose-code:before:content-[''] prose-code:after:content-['']
  prose-pre:bg-surface-2 dark:prose-pre:bg-background prose-pre:border prose-pre:border-border dark:prose-pre:border-border
  prose-pre:my-5 prose-pre:p-4 prose-pre:rounded-lg prose-pre:overflow-x-auto
  prose-hr:border-border dark:prose-hr:border-border prose-hr:my-8
  [&>*:first-child]:mt-0 [&>*:last-child]:mb-0
  [&_ul]:list-disc [&_ul]:pl-6
  [&_ol]:list-decimal [&_ol]:pl-6`;

// A rendered markdown table wrapped in a horizontal-scroll container with an
// Export (Excel / CSV) dropdown — reads the DOM table so it exports exactly
// what's shown.
function MarkdownTable({ children, ...props }: React.HTMLAttributes<HTMLTableElement>) {
  const tableRef = useRef<HTMLTableElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const handleExport = useCallback((kind: "excel" | "csv") => {
    setMenuOpen(false);
    const table = tableRef.current;
    if (!table) return;
    try {
      if (kind === "excel") exportTableToExcel(table);
      else exportTableToCSV(table);
    } catch {
      /* nothing to export */
    }
  }, []);

  return (
    <div className="my-5 group/table relative">
      <div className="flex justify-end mb-1.5">
        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            onBlur={() => setTimeout(() => setMenuOpen(false), 120)}
            className="inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-1 rounded-md border border-border dark:border-border bg-surface-2 dark:bg-card text-muted-foreground dark:text-foreground hover:bg-secondary dark:hover:bg-accent transition-colors"
            title="Export table"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Export
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 z-20 min-w-[130px] rounded-lg border border-border dark:border-border bg-card shadow-lg overflow-hidden">
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => handleExport("excel")}
                className="w-full flex items-center gap-2 px-3 py-2 text-[12px] text-foreground hover:bg-accent/60 transition-colors"
              >
                <svg className="w-3.5 h-3.5 text-brand" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
                Excel (.xlsx)
              </button>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => handleExport("csv")}
                className="w-full flex items-center gap-2 px-3 py-2 text-[12px] text-foreground hover:bg-accent/60 transition-colors border-t border-border"
              >
                <svg className="w-3.5 h-3.5 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
                CSV (.csv)
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border dark:border-border tactical-scrollbar">
        <table
          ref={tableRef}
          className="w-full text-sm border-collapse [&_th]:bg-surface-2 dark:[&_th]:bg-card [&_th]:text-foreground [&_th]:font-semibold [&_th]:text-left [&_th]:px-3 [&_th]:py-2 [&_th]:border-b [&_th]:border-border [&_td]:px-3 [&_td]:py-2 [&_td]:border-t [&_td]:border-border [&_td]:text-muted-foreground dark:[&_td]:text-foreground [&_tbody_tr:hover]:bg-accent/40"
          {...props}
        >
          {children}
        </table>
      </div>
    </div>
  );
}

// Plain external link (used when there's no citation context, e.g. streaming).
const PlainLink = ({ node, href, children, ...props }: any) => (
  <a
    href={href}
    target="_blank"
    rel="noopener noreferrer"
    {...props}
    className="text-foreground dark:text-foreground underline underline-offset-4 hover:text-muted-foreground dark:hover:text-foreground"
  >
    {children}
  </a>
);

// Turn bare [n] references into links (#source-n) the citation renderer picks
// up. Only done once the message is finished and has sources — during
// streaming the [n] stays as plain text.
function processContent(content: string, sources?: DocumentSource[]): string {
  if (!sources || sources.length === 0) return content;
  return content.replace(/\[\s*(\d+)\s*\]/g, (match, id) => {
    const index = parseInt(id, 10);
    if (index > 0 && index <= sources.length) return ` [${index}](#source-${index})`;
    return match;
  });
}

export interface CitationContext {
  message: ChatMessage;
  sourceUrls: Map<string, string>;
  onCitationHover: (index: number, messageId: string, x: number, y: number) => void;
  onCitationLeave: () => void;
  onCitationClick: (source: DocumentSource, url: string | undefined) => void;
}

const MarkdownContent = React.memo(function MarkdownContent({
  content,
  citation,
}: {
  content: string;
  citation?: CitationContext;
}) {
  const components = useMemo(() => {
    // No citation context (e.g. streaming view) → plain links only.
    if (!citation) {
      return { table: MarkdownTable as any, a: PlainLink };
    }

    const { message, sourceUrls, onCitationHover, onCitationLeave, onCitationClick } = citation;

    const CitationLink = ({ node, href, children, ...props }: any) => {
      if (typeof href === "string" && href.startsWith("#source-")) {
        const index = parseInt(href.replace("#source-", ""), 10);
        const source = message.sources?.[index - 1] as DocumentSource | undefined;
        if (!isNaN(index) && source) {
          const finalUrl = source.file_key ? sourceUrls.get(source.file_key) : undefined;
          return (
            <span
              className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 ml-0.5 text-[10px] font-semibold text-muted-foreground dark:text-foreground bg-secondary dark:bg-card border border-border dark:border-border rounded-md cursor-pointer hover:bg-secondary dark:hover:bg-accent transition-colors align-super"
              onMouseEnter={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                onCitationHover(index - 1, message.id, rect.left + rect.width / 2, rect.top);
              }}
              onMouseLeave={onCitationLeave}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onCitationClick(source, finalUrl);
              }}
            >
              {index}
            </span>
          );
        }
      }
      return <PlainLink href={href} {...props}>{children}</PlainLink>;
    };

    return { table: MarkdownTable as any, a: CitationLink };
  }, [citation]);

  const rendered = citation ? processContent(content, citation.message.sources as DocumentSource[]) : content;

  return (
    <div className={PROSE_CLASSES}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {rendered}
      </ReactMarkdown>
    </div>
  );
});

export default MarkdownContent;
