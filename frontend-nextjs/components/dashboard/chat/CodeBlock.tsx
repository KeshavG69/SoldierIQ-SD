"use client";

/**
 * Fenced code block in chat answers, styled like Claude / ChatGPT: a plain rounded
 * panel with syntax colours (One Dark / One Light, following the app theme), a
 * copy button in the corner, and long lines wrapped instead of scrolling.
 */

import { memo, useState } from "react";
import { Highlight, themes } from "prism-react-renderer";
import { Check, Copy } from "lucide-react";
import { useThemeStore } from "@/lib/stores/themeStore";

// Common aliases → the grammar names prism-react-renderer ships.
const LANGUAGE_ALIASES: Record<string, string> = {
  py: "python",
  js: "javascript",
  ts: "typescript",
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  yml: "yaml",
  md: "markdown",
  html: "markup",
  xml: "markup",
};

function CodeBlock({ code, language }: { code: string; language?: string }) {
  const isDark = useThemeStore((s) => s.theme) === "dark";
  const [copied, setCopied] = useState(false);
  const lang = LANGUAGE_ALIASES[(language || "").toLowerCase()] || (language || "").toLowerCase() || "text";
  const source = code.replace(/\n$/, "");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(source);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — nothing to do */
    }
  };

  return (
    <div className="not-prose group relative rounded-xl border border-border bg-[#fafafa] dark:bg-[#1e1e1e]">
      <button
        type="button"
        onClick={copy}
        className="absolute right-3 top-3 inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
        aria-label={copied ? "Copied" : "Copy code"}
        title={copied ? "Copied" : "Copy"}
      >
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      </button>
      <Highlight code={source} language={lang} theme={isDark ? themes.oneDark : themes.oneLight}>
        {({ style, tokens, getLineProps, getTokenProps }) => (
          <pre
            className="m-0 overflow-x-auto bg-transparent py-4 pl-5 pr-12 text-[13.5px] leading-[1.7] whitespace-pre-wrap break-words"
            style={{
              // theme's plain text colour, our own panel background
              color: style.color,
              fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, monospace',
            }}
          >
            <code>
              {tokens.map((line, i) => {
                const { key: _lk, ...lineProps } = getLineProps({ line }) as any;
                return (
                  <div key={i} {...lineProps} style={undefined}>
                    {line.map((token, j) => {
                      const { key: _tk, ...tokenProps } = getTokenProps({ token }) as any;
                      return <span key={j} {...tokenProps} />;
                    })}
                  </div>
                );
              })}
            </code>
          </pre>
        )}
      </Highlight>
    </div>
  );
}

export default memo(CodeBlock);
