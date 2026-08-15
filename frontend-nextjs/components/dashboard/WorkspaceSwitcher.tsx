"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { workspaceApi, WorkspaceOrganization } from "@/lib/api/workspace";

/**
 * Organization switcher. Shows the active org; with more than one membership it
 * opens a dropdown to switch. Switching calls the backend (which returns fresh
 * tokens), drops per-org caches, and reloads so everything refetches under the
 * new organization.
 */
export default function WorkspaceSwitcher() {
  const [orgs, setOrgs] = useState<WorkspaceOrganization[]>([]);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    workspaceApi.getUserOrganizations().then(setOrgs).catch(() => setOrgs([]));
  }, []);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const current = orgs.find((o) => o.is_current) || orgs[0];

  const handleSwitch = useCallback(
    async (id: string) => {
      if (switching) return;
      setSwitching(id);
      try {
        await workspaceApi.switchOrganization(id);
        try {
          localStorage.removeItem("soldieriq-documents-cache");
          localStorage.removeItem("soldieriq-chat-session");
        } catch {
          /* ignore */
        }
        window.location.reload();
      } catch {
        setSwitching(null);
      }
    },
    [switching]
  );

  if (!current) return null;

  const Badge = ({ name }: { name: string }) => (
    <span className="w-5 h-5 rounded-md bg-brand/15 text-brand text-[10px] font-bold flex items-center justify-center flex-shrink-0">
      {name.charAt(0).toUpperCase()}
    </span>
  );

  // Single org → static pill.
  if (orgs.length <= 1) {
    return (
      <div className="inline-flex items-center gap-2 px-2.5 h-8 rounded-lg bg-surface-2 border border-border">
        <Badge name={current.name} />
        <span className="text-xs font-medium text-foreground max-w-[150px] truncate">{current.name}</span>
      </div>
    );
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-2 px-2.5 h-8 rounded-lg bg-surface-2 border border-border hover:border-brand/40 hover:bg-accent transition-colors"
      >
        <Badge name={current.name} />
        <span className="text-xs font-medium text-foreground max-w-[150px] truncate">{current.name}</span>
        <svg
          className={`w-3.5 h-3.5 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1.5 w-64 rounded-xl bg-card border border-border shadow-lg overflow-hidden z-50">
          <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground border-b border-border">
            Organizations
          </div>
          <div className="p-1 max-h-72 overflow-y-auto">
            {orgs.map((o) => (
              <button
                key={o.id}
                onClick={() => (o.is_current ? setOpen(false) : handleSwitch(o.id))}
                className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-colors ${
                  o.is_current ? "bg-brand/[0.08]" : "hover:bg-accent"
                }`}
              >
                <span className="w-7 h-7 rounded-md bg-brand/15 text-brand text-[11px] font-bold flex items-center justify-center flex-shrink-0">
                  {o.name.charAt(0).toUpperCase()}
                </span>
                <span className="flex-1 min-w-0">
                  <span className="block text-sm font-medium text-foreground truncate">{o.name}</span>
                  <span className="block text-[11px] text-muted-foreground capitalize">{o.role}</span>
                </span>
                {switching === o.id ? (
                  <span className="w-3.5 h-3.5 border-2 border-brand/30 border-t-brand rounded-full animate-spin" />
                ) : o.is_current ? (
                  <svg className="w-4 h-4 text-brand flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-8 8a1 1 0 01-1.4 0l-4-4a1 1 0 011.4-1.4L8 12.6l7.3-7.3a1 1 0 011.4 0z" clipRule="evenodd" />
                  </svg>
                ) : null}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
