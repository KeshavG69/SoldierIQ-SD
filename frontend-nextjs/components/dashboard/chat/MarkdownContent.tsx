"use client";

import React, { useRef, useState, useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { exportTableToExcel, exportTableToCSV, sanitizeFileName } from "@/lib/chat/exportTable";
import { ChatMessage } from "@/types";
import { DocumentSource } from "@/lib/stores/chatStore";

// Shared markdown renderer for assistant answers, used by both the finished
// message and the streaming view so rendering stays identical. Ported from Kroolo
// enterprise's chat MarkdownRenderer: the same element map (heading-1…6,
// paragraph-body, ordered/unordered lists, window-style code blocks, ruled tables
// with an export button underneath) styled by app/markdown-renderer.css.

export const PROSE_CLASSES = "prose prose-h1:text-xl dark:prose-invert siq-md-renderer";

// react-markdown passes the hast `node`; never forward it to the DOM.
const strip = (props: Record<string, any>) => {
  const { node, ...rest } = props;
  return rest;
};

const cx = (...parts: (string | undefined | false)[]) => parts.filter(Boolean).join(" ");

const UnorderedList = ({ className, ...props }: any) => (
  <ul className={cx(className, "paragraph-body", "unordered-list")} {...strip(props)} />
);
const OrderedList = ({ className, ...props }: any) => (
  <ol className={cx(className, "paragraph-body", "ordered-list")} {...strip(props)} />
);
const Paragraph = ({ className, ...props }: any) => (
  <p className={cx(className, "paragraph-body")} {...strip(props)} />
);
const EmphasizedText = ({ className, ...props }: any) => (
  <em className={cx(className, "emphasized-text")} {...strip(props)} />
);
const ItalicText = ({ className, ...props }: any) => (
  <i className={cx(className, "italic-text", "paragraph-body")} {...strip(props)} />
);
const StrongText = ({ className, ...props }: any) => (
  <strong className={cx(className, "strong-text")} {...strip(props)} />
);
const BoldText = ({ className, ...props }: any) => (
  <b className={cx(className, "bold-text")} {...strip(props)} />
);
const UnderlinedText = ({ className, ...props }: any) => (
  <u className={cx(className, "underlined-text", "paragraph-body")} {...strip(props)} />
);
const DeletedText = ({ className, ...props }: any) => (
  <del className={cx(className, "deleted-text", "paragraph-body")} {...strip(props)} />
);
const HorizontalRule = ({ className, ...props }: any) => (
  <hr className={cx(className, "horizontal-rule")} {...strip(props)} />
);
const Blockquote = ({ className, ...props }: any) => (
  <blockquote className={cx(className, "blockquote-text", "paragraph-body")} {...strip(props)} />
);
const Heading = (level: 1 | 2 | 3 | 4 | 5 | 6) => {
  const Tag = `h${level}` as const;
  const H = ({ className, ...props }: any) => <Tag className={cx(className, `heading-${level}`)} {...strip(props)} />;
  H.displayName = `Heading${level}`;
  return H;
};
const Img = ({ src, alt, ...props }: any) => (
  <span className="image-container block">
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src={src} alt={alt ?? "Rendered image"} className="image-element" {...strip(props)} />
  </span>
);

// Inline `code` is a pill; a fenced block with a language gets the window-style
// header (three dots + language label) over a dark body, as in enterprise.
const Code = ({ children, className, ...props }: any) => {
  const content = String(children ?? "").trim();
  const match = /language-([\w-]+)/.exec(className || "");
  const isBlock = !!match || content.includes("\n");
  if (!isBlock || content === "#" || content === "$") {
    return (
      <code className={cx("inline-code", className)} {...strip(props)}>
        {children}
      </code>
    );
  }
  return (
    <div className="inline-code-container">
      <div className="inline-code-header">
        <div className="inline-code-dots">
          <div className="inline-code-dot inline-code-dot-red" />
          <div className="inline-code-dot inline-code-dot-yellow" />
          <div className="inline-code-dot inline-code-dot-green" />
        </div>
        <span className="inline-code-label">{match ? match[1] : "Code"}</span>
      </div>
      <pre className="inline-code-pre">
        <code className="inline-code-element">{children}</code>
      </pre>
    </div>
  );
};
// The code component draws its own <pre>; don't wrap it in another.
const Pre = ({ children }: any) => <>{children}</>;

// Ruled table with an Export (Excel / CSV) button underneath — reads the DOM
// table so it exports exactly what's shown.
function MarkdownTable({ className, ...props }: any) {
  const tableRef = useRef<HTMLTableElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const handleExport = useCallback((kind: "excel" | "csv") => {
    setMenuOpen(false);
    const table = tableRef.current;
    if (!table) return;
    const fileName = sanitizeFileName(`table-export-${new Date().toISOString().slice(0, 10)}`);
    try {
      if (kind === "excel") exportTableToExcel(table, fileName);
      else exportTableToCSV(table, fileName);
    } catch {
      /* nothing to export */
    }
  }, []);

  return (
    <div className="table-wrapper not-prose">
      <div className="table-container">
        <div className="table-scroll tactical-scrollbar">
          <table ref={tableRef} className={cx(className, "table-element")} {...strip(props)} />
        </div>
      </div>
      <div className="flex justify-end mt-2">
        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            onBlur={() => setTimeout(() => setMenuOpen(false), 120)}
            className="flex items-center cursor-pointer rounded-lg px-2 py-1 text-muted-foreground hover:text-foreground transition-colors"
            title="Export"
            aria-label="Export table"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 z-20 min-w-[160px] rounded-lg border border-border bg-card shadow-lg overflow-hidden">
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => handleExport("excel")}
                className="w-full flex items-center gap-2 px-3 py-2 text-[13px] text-foreground hover:bg-accent/60 transition-colors"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><path d="M8 13h8M8 17h8M12 11v8" /></svg>
                Export as Excel
              </button>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => handleExport("csv")}
                className="w-full flex items-center gap-2 px-3 py-2 text-[13px] text-foreground hover:bg-accent/60 transition-colors border-t border-border"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><path d="M16 13H8M16 17H8M10 9H8" /></svg>
                Export as CSV
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const TableHead = ({ className, ...props }: any) => <thead className={cx(className, "table-head")} {...strip(props)} />;
const TableHeadCell = ({ className, ...props }: any) => <th className={cx(className, "table-head-cell")} {...strip(props)} />;
const TableBody = ({ className, ...props }: any) => <tbody className={cx(className, "table-body")} {...strip(props)} />;
const TableRow = ({ className, ...props }: any) => <tr className={cx(className, "table-row")} {...strip(props)} />;
const TableCell = ({ className, ...props }: any) => <td className={cx(className, "table-cell")} {...strip(props)} />;

// Enterprise's element map (chat/ui/typography/MarkdownRenderer/styles.tsx).
// `a` is added per render below (plain link vs. citation pill).
const BASE_COMPONENTS = {
  h1: Heading(1),
  h2: Heading(2),
  h3: Heading(3),
  h4: Heading(4),
  h5: Heading(5),
  h6: Heading(6),
  ul: UnorderedList,
  ol: OrderedList,
  em: EmphasizedText,
  i: ItalicText,
  strong: StrongText,
  b: BoldText,
  u: UnderlinedText,
  del: DeletedText,
  hr: HorizontalRule,
  blockquote: Blockquote,
  code: Code,
  pre: Pre,
  img: Img,
  p: Paragraph,
  table: MarkdownTable,
  thead: TableHead,
  th: TableHeadCell,
  tbody: TableBody,
  tr: TableRow,
  td: TableCell,
};

// Plain external link (used when there's no citation context, e.g. streaming).
const PlainLink = ({ node, href, children, ...props }: any) => (
  <a
    href={href}
    target="_blank"
    rel="noopener noreferrer"
    {...props}
    className="anchor-link hover:text-muted-foreground"
  >
    {children}
  </a>
);

// Turn bare [n] references into links (#source-n) the citation renderer picks
// up. Only done once the message is finished and has sources — during
// streaming the [n] stays as plain text.
//
// The model is instructed to cite the 1-based source number ([1], [2], …). As
// a safety net we also repair raw-id citations it sometimes leaks — the chunk
// id ("<document_id>::<seq>") or a bare document id — by mapping the document
// id back to its first source index. Without this those tags fail to match and
// render as literal text like "[c889b68e-…::0]" in the answer.
function processContent(content: string, sources?: DocumentSource[]): string {
  if (!sources || sources.length === 0) return content;

  const docToIndex = new Map<string, number>();
  sources.forEach((s, i) => {
    if (s.document_id && !docToIndex.has(s.document_id)) {
      docToIndex.set(s.document_id, i + 1);
    }
  });

  // One capture group per bracketed token; the callback decides how to resolve
  // it. Non-citation brackets (real markdown link text, etc.) fall through
  // unchanged, so [label](url) links are preserved.
  return content.replace(/\[\s*([^\]]+?)\s*\]/g, (match, inner: string) => {
    // Correct form: a plain source number, or a grouped citation like
    // "[11, 12, 13]" the model sometimes emits when several sources back the
    // same statement. Expand the group into individual [n](#source-n) tags so
    // each renders as its own citation pill instead of literal "[11, 12, 13]".
    if (/^\d+(?:\s*,\s*\d+)*$/.test(inner)) {
      const nums = inner.split(",").map((n) => parseInt(n.trim(), 10));
      // Only rewrite when every number is a valid source index; otherwise leave
      // the bracket untouched so non-citation text (e.g. "[1, 2]" ranges in
      // prose) isn't mangled.
      if (nums.every((n) => n > 0 && n <= sources.length)) {
        return nums.map((n) => ` [${n}](#source-${n})`).join("");
      }
      return match;
    }
    // Leaked raw id: "<uuid>::<seq>" or a bare "<uuid>". Resolve by document id.
    if (/^[0-9a-fA-F-]{8,}(::\d+)?$/.test(inner)) {
      const docId = inner.split("::")[0];
      const index = docToIndex.get(docId);
      if (index) return ` [${index}](#source-${index})`;
    }
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
      return { ...BASE_COMPONENTS, a: PlainLink };
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

    return { ...BASE_COMPONENTS, a: CitationLink };
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
