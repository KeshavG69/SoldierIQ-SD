"use client";

/**
 * Live timeline of the agent's tool calls (port of enterprise's
 * StreamingToolCalls / TimelineStepsSummary), for every tool: knowledge-base
 * search, TAK, Composio setup and every Composio action.
 *
 *   - While the answer streams: the last few steps as a vertical timeline, the
 *     running one with a shimmering label, finished ones with a ✓ + duration.
 *   - Once done: collapses to "✓ N steps completed ›", expandable.
 *   - Any step can be opened to see its arguments and a result preview.
 */

import { memo, useEffect, useRef, useState } from "react";
import { ToolCallStep } from "@/types";

const STREAMING_VISIBLE_LIMIT = 3;

function formatDuration(seconds?: number): string | null {
  if (seconds == null || !isFinite(seconds)) return null;
  return seconds < 1 ? `${Math.max(1, Math.round(seconds * 1000))}ms` : `${seconds.toFixed(1)}s`;
}

function StepIcon({ step }: { step: ToolCallStep }) {
  const [logoFailed, setLogoFailed] = useState(false);
  if (step.logo && !logoFailed) {
    return (
      <div className="w-5 h-5 rounded bg-white border border-border flex items-center justify-center overflow-hidden">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={step.logo} alt="" className="w-3.5 h-3.5 object-contain" onError={() => setLogoFailed(true)} />
      </div>
    );
  }
  const paths: Record<string, React.ReactNode> = {
    search: <><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></>,
    map: <><path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z" /><circle cx="12" cy="10" r="2.5" /></>,
    message: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
    route: <><circle cx="6" cy="19" r="2.5" /><circle cx="18" cy="5" r="2.5" /><path d="M8.5 19H16a3.5 3.5 0 0 0 0-7H8a3.5 3.5 0 0 1 0-7h7.5" /></>,
    plug: <path d="M12 22v-5M9 8V2M15 8V2M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z" />,
  };
  return (
    <div className="w-5 h-5 rounded bg-surface-2 dark:bg-card border border-border flex items-center justify-center text-muted-foreground">
      <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        {paths[step.icon || ""] ?? <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-2.4z" />}
      </svg>
    </div>
  );
}

function StatusMark({ status }: { status: ToolCallStep["status"] }) {
  if (status === "running") {
    return <div className="w-3.5 h-3.5 border-2 border-border border-t-brand rounded-full animate-spin" aria-label="Running" />;
  }
  if (status === "error") {
    return (
      <svg className="w-3.5 h-3.5 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-label="Failed">
        <path d="M18 6L6 18M6 6l12 12" />
      </svg>
    );
  }
  return (
    <svg className="w-3.5 h-3.5 text-emerald-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-label="Done">
      <path d="M20 6L9 17l-5-5" />
    </svg>
  );
}

const StepRow = memo(function StepRow({ step, isLast }: { step: ToolCallStep; isLast: boolean }) {
  const [open, setOpen] = useState(false);
  const running = step.status === "running";
  const label = running ? step.label : step.doneLabel || step.label;
  const duration = !running ? formatDuration(step.duration) : null;
  const hasDetails = (step.args && Object.keys(step.args).length > 0) || !!step.resultPreview;

  return (
    <div className="relative animate-in fade-in slide-in-from-bottom-1 duration-300">
      {!isLast && <div className="absolute left-[9.5px] top-7 bottom-0 w-px bg-border" aria-hidden />}
      <button
        type="button"
        onClick={() => hasDetails && setOpen((o) => !o)}
        className={`w-full flex items-start gap-2.5 rounded-md px-1 py-1 text-left ${
          hasDetails ? "hover:bg-secondary/60 dark:hover:bg-accent/40 cursor-pointer" : "cursor-default"
        }`}
        aria-expanded={hasDetails ? open : undefined}
      >
        <div className="relative z-10 mt-0.5 shrink-0 bg-background">
          <StepIcon step={step} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 min-w-0">
            {step.app && <span className="text-[12px] font-medium text-foreground shrink-0">{step.app}</span>}
            <span className={`text-[13px] truncate ${running ? "tool-shimmer" : "text-muted-foreground"}`}>{label}</span>
            <span className="ml-auto flex items-center gap-1.5 shrink-0">
              {duration && <span className="text-[11px] text-muted-foreground tabular-nums">{duration}</span>}
              <StatusMark status={step.status} />
            </span>
          </div>
          {step.detail && <p className="text-[12px] text-muted-foreground/85 truncate mt-0.5">{step.detail}</p>}
        </div>
      </button>

      {open && hasDetails && (
        <div className="ml-8 mt-1 mb-2 rounded-lg border border-border bg-surface-2 dark:bg-card/60 p-2.5 space-y-2 animate-in fade-in slide-in-from-top-1 duration-200">
          {step.args && Object.keys(step.args).length > 0 && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">Input</div>
              <pre className="text-[11px] leading-relaxed text-foreground whitespace-pre-wrap break-words max-h-40 overflow-auto">
                {JSON.stringify(step.args, null, 2)}
              </pre>
            </div>
          )}
          {step.resultPreview && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">Result</div>
              <pre className="text-[11px] leading-relaxed text-foreground whitespace-pre-wrap break-words max-h-56 overflow-auto">
                {step.resultPreview}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
});

export default function ToolCallTimeline({ steps, isStreaming }: { steps: ToolCallStep[]; isStreaming: boolean }) {
  // Expanded while streaming; collapse to a summary once the answer is done.
  const [expanded, setExpanded] = useState(isStreaming);
  const wasStreaming = useRef(isStreaming);
  useEffect(() => {
    if (wasStreaming.current && !isStreaming) setExpanded(false);
    wasStreaming.current = isStreaming;
  }, [isStreaming]);

  if (!steps.length) return null;

  if (isStreaming) {
    const visible = steps.slice(-STREAMING_VISIBLE_LIMIT);
    const hidden = steps.length - visible.length;
    return (
      <div className="mb-3">
        {hidden > 0 && (
          <div className="text-[11px] text-muted-foreground mb-1 pl-1">
            {hidden} earlier step{hidden === 1 ? "" : "s"}
          </div>
        )}
        {visible.map((s, i) => (
          <StepRow key={s.id} step={s} isLast={i === visible.length - 1} />
        ))}
      </div>
    );
  }

  const failed = steps.filter((s) => s.status === "error").length;
  const completed = steps.length - failed;
  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center gap-1.5 py-0.5 text-[13px] text-muted-foreground hover:text-foreground transition-colors select-none"
        aria-expanded={expanded}
      >
        <StatusMark status={failed && !completed ? "error" : "done"} />
        <span>
          {completed} step{completed === 1 ? "" : "s"} completed
          {failed > 0 && `, ${failed} failed`}
        </span>
        <svg
          className={`w-3 h-3 opacity-60 transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>
      {expanded && (
        <div className="mt-1 animate-in fade-in slide-in-from-top-1 duration-200">
          {steps.map((s, i) => (
            <StepRow key={s.id} step={s} isLast={i === steps.length - 1} />
          ))}
        </div>
      )}
    </div>
  );
}
