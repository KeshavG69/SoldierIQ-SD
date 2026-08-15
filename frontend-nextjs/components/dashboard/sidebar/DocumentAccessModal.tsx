"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Document } from "@/types";
import { organizationsApi, OrgMember } from "@/lib/api/organizations";
import { documentAccessApi } from "@/lib/api/documentAccess";
import { Z_INDEX } from "@/lib/constants/zIndex";

// iOS-style toggle in the olive brand palette. On = filled brand, off = surface.
function Toggle({
  on,
  disabled,
  onClick,
}: {
  on: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={disabled}
      onClick={onClick}
      className={`relative w-9 h-5 rounded-full transition-colors flex-shrink-0 disabled:opacity-60 disabled:cursor-not-allowed ${
        on ? "bg-brand" : "bg-surface-2 border border-border"
      }`}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
          on ? "translate-x-4" : ""
        }`}
      />
    </button>
  );
}

/**
 * Admin-only panel to control which members can see and query one document.
 *
 * Each non-admin member gets a toggle: on = access granted (a graph HAS_ACCESS
 * edge), off = hidden from their list and their search. Admins always have
 * access, so they're shown as "Always" with no toggle.
 *
 * Rendered through a portal to document.body — the sidebar rows live inside
 * framer-motion transforms, which would otherwise trap `position: fixed`.
 */
export default function DocumentAccessModal({
  document: doc,
  onClose,
}: {
  document: Document;
  onClose: () => void;
}) {
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [granted, setGranted] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [mem, access] = await Promise.all([
        organizationsApi.listMembers(),
        documentAccessApi.getAccess(doc.id),
      ]);
      setMembers(mem);
      setGranted(new Set((access.emails || []).map((e) => e.toLowerCase())));
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to load access.");
    } finally {
      setLoading(false);
    }
  }, [doc.id]);

  useEffect(() => {
    load();
  }, [load]);

  // Close on Escape for keyboard users.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggle = async (m: OrgMember) => {
    const email = (m.email || "").trim();
    if (!email) return;
    const key = email.toLowerCase();
    const currentlyOn = granted.has(key);
    setBusy(key);
    setError(null);
    // Optimistic flip — revert if the request fails.
    setGranted((s) => {
      const n = new Set(s);
      if (currentlyOn) n.delete(key);
      else n.add(key);
      return n;
    });
    try {
      if (currentlyOn) await documentAccessApi.revoke(doc.id, email);
      else await documentAccessApi.grant(doc.id, email);
    } catch (e: any) {
      setGranted((s) => {
        const n = new Set(s);
        if (currentlyOn) n.add(key);
        else n.delete(key);
        return n;
      });
      setError(e?.response?.data?.detail || "Failed to update access.");
    } finally {
      setBusy(null);
    }
  };

  const displayName = (m: OrgMember) =>
    [m.firstName, m.lastName].filter(Boolean).join(" ") || m.username || m.email || "Member";

  const regular = members.filter((m) => m.role !== "admin");
  const grantedCount = regular.filter((m) =>
    granted.has((m.email || "").toLowerCase())
  ).length;

  if (typeof document === "undefined") return null;

  return createPortal(
    <>
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        style={{ zIndex: Z_INDEX.MODAL }}
        onClick={onClose}
      />
      <div
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-lg px-4"
        style={{ zIndex: Z_INDEX.MODAL + 1 }}
      >
        <div className="rounded-2xl bg-card border border-border shadow-2xl overflow-hidden max-h-[85vh] flex flex-col">
          {/* Header */}
          <div className="px-6 py-4 border-b border-border flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-foreground">Document access</h2>
              <p className="text-xs text-muted-foreground mt-0.5 truncate">{doc.file_name}</p>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-muted-foreground hover:bg-accent transition-colors flex-shrink-0"
              aria-label="Close"
            >
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Body */}
          <div className="overflow-y-auto p-6 space-y-4">
            <p className="text-xs text-muted-foreground leading-relaxed">
              Admins can see every document. Choose which members can see and query{" "}
              <span className="text-foreground font-medium">this</span> one.
            </p>
            {error && <p className="text-xs text-red-500">{error}</p>}

            {loading ? (
              <div className="py-6 flex justify-center">
                <span className="w-5 h-5 border-2 border-brand/30 border-t-brand rounded-full animate-spin" />
              </div>
            ) : members.length === 0 ? (
              <p className="text-xs text-muted-foreground">No members in this organization yet.</p>
            ) : (
              <div className="space-y-1">
                {members.map((m) => {
                  const isAdminMember = m.role === "admin";
                  const key = (m.email || "").toLowerCase();
                  const on = isAdminMember || granted.has(key);
                  const noEmail = !m.email;
                  return (
                    <div
                      key={m.user_id}
                      className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-accent/50"
                    >
                      <span className="w-8 h-8 rounded-full bg-brand/15 text-brand text-xs font-bold flex items-center justify-center flex-shrink-0">
                        {displayName(m).charAt(0).toUpperCase()}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-foreground truncate">
                          {displayName(m)}{" "}
                          {m.is_self && (
                            <span className="text-[11px] text-muted-foreground">(you)</span>
                          )}
                        </div>
                        <div className="text-[11px] text-muted-foreground truncate">
                          {m.email || "no email"}
                        </div>
                      </div>
                      {isAdminMember ? (
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-brand/80 flex-shrink-0">
                          Always
                        </span>
                      ) : noEmail ? (
                        <span className="text-[10px] text-muted-foreground flex-shrink-0">—</span>
                      ) : (
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {busy === key && (
                            <span className="w-3.5 h-3.5 border-2 border-brand/30 border-t-brand rounded-full animate-spin" />
                          )}
                          <Toggle on={on} disabled={busy === key} onClick={() => toggle(m)} />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-3 border-t border-border flex items-center justify-between">
            <span className="text-[11px] text-muted-foreground">
              {grantedCount} member{grantedCount === 1 ? "" : "s"} granted
            </span>
            <button
              onClick={onClose}
              className="px-4 py-1.5 rounded-lg bg-brand text-brand-foreground text-sm font-medium hover:bg-brand-hover shadow-accent transition-all"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    </>,
    document.body
  );
}
