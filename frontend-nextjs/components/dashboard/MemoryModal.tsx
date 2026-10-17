"use client";

/**
 * Memory — what the chat agent remembers about the current user.
 *
 * The agent saves long-term memories after each chat (Agno, Postgres) and
 * reads them into its context. Here the user can review them, correct the
 * wording or topics, add their own, delete one, or clear them all. Scoped to
 * the active organization.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { memoryApi, Memory } from "@/lib/api/memory";
import { Z_INDEX } from "@/lib/constants/zIndex";

const inputClass =
  "w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15 transition-all";

function parseTopics(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
    .slice(0, 10);
}

function formatDate(epoch: number | null): string {
  if (!epoch) return "";
  return new Date(epoch * 1000).toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" });
}

function errorText(e: any, fallback: string): string {
  return e?.response?.data?.detail || e?.message || fallback;
}

export default function MemoryModal({ onClose }: { onClose: () => void }) {
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [limit, setLimit] = useState(20);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const [adding, setAdding] = useState(false);
  const [newText, setNewText] = useState("");
  const [newTopics, setNewTopics] = useState("");

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [editTopics, setEditTopics] = useState("");

  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [busy, setBusy] = useState<string | null>(null); // memory id, "add" or "clear"

  const load = useCallback(async () => {
    try {
      const res = await memoryApi.list();
      setMemories(res.memories);
      setLimit(res.limit);
    } catch (e: any) {
      setError(errorText(e, "Failed to load memories."));
      setMemories((prev) => prev ?? []);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!memories || !q) return memories ?? [];
    return memories.filter(
      (m) => m.memory.toLowerCase().includes(q) || m.topics.some((t) => t.toLowerCase().includes(q))
    );
  }, [memories, query]);

  const onAdd = async () => {
    if (!newText.trim()) return;
    setBusy("add");
    setError(null);
    try {
      await memoryApi.add(newText.trim(), parseTopics(newTopics));
      setNewText("");
      setNewTopics("");
      setAdding(false);
      await load(); // the server may have dropped the oldest to stay under the limit
    } catch (e: any) {
      setError(errorText(e, "Could not add memory."));
    } finally {
      setBusy(null);
    }
  };

  const startEdit = (m: Memory) => {
    setEditingId(m.id);
    setEditText(m.memory);
    setEditTopics(m.topics.join(", "));
    setConfirmDeleteId(null);
  };

  const onSaveEdit = async (id: string) => {
    if (!editText.trim()) return;
    setBusy(id);
    setError(null);
    try {
      const saved = await memoryApi.update(id, editText.trim(), parseTopics(editTopics));
      setMemories((prev) => (prev ? [saved, ...prev.filter((m) => m.id !== id)] : prev));
      setEditingId(null);
    } catch (e: any) {
      setError(errorText(e, "Could not save memory."));
    } finally {
      setBusy(null);
    }
  };

  const onDelete = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      await memoryApi.remove(id);
      setMemories((prev) => (prev ? prev.filter((m) => m.id !== id) : prev));
      setConfirmDeleteId(null);
    } catch (e: any) {
      setError(errorText(e, "Could not delete memory."));
    } finally {
      setBusy(null);
    }
  };

  const onClear = async () => {
    setBusy("clear");
    setError(null);
    try {
      await memoryApi.clear();
      setMemories([]);
      setConfirmClear(false);
    } catch (e: any) {
      setError(errorText(e, "Could not clear memories."));
    } finally {
      setBusy(null);
    }
  };

  const count = memories?.length ?? 0;

  return (
    <>
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" style={{ zIndex: Z_INDEX.MODAL }} onClick={onClose} />
      <div
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-2xl px-4"
        style={{ zIndex: Z_INDEX.MODAL + 1 }}
      >
        <div className="rounded-2xl bg-card border border-border shadow-2xl overflow-hidden max-h-[85vh] flex flex-col">
          <div className="px-6 py-4 border-b border-border flex items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold text-foreground">Memory</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                What the assistant remembers about you from your chats. Edit or delete anything that's wrong.
              </p>
            </div>
            <div className="flex items-center gap-3">
              {memories && (
                <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap bg-secondary text-muted-foreground">
                  {count}/{limit} saved
                </span>
              )}
              <button onClick={onClose} className="p-1.5 rounded-md text-muted-foreground hover:bg-accent transition-colors" aria-label="Close">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
          </div>

          <div className="px-6 pt-4 flex gap-2">
            <input
              className={inputClass}
              placeholder="Search memories"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {!adding && (
              <button
                onClick={() => {
                  setAdding(true);
                  setEditingId(null);
                }}
                className="px-3 py-2 rounded-lg bg-brand text-brand-foreground text-sm font-medium hover:bg-brand-hover whitespace-nowrap transition-colors"
              >
                Add memory
              </button>
            )}
          </div>

          {error && (
            <div className="mx-6 mt-3 px-3 py-2 rounded-lg border border-red-500/30 bg-red-500/10 text-xs text-red-500">{error}</div>
          )}

          <div className="overflow-y-auto p-6 space-y-3">
            {adding && (
              <div className="rounded-xl border border-brand/40 p-3 space-y-2">
                <textarea
                  className={`${inputClass} resize-none`}
                  rows={2}
                  autoFocus
                  maxLength={2000}
                  placeholder="Something the assistant should remember, e.g. I'm the S2 for 3rd Battalion"
                  value={newText}
                  onChange={(e) => setNewText(e.target.value)}
                />
                <input
                  className={inputClass}
                  placeholder="Topics (optional, comma-separated)"
                  value={newTopics}
                  onChange={(e) => setNewTopics(e.target.value)}
                />
                <div className="flex justify-end gap-2">
                  <button
                    onClick={() => {
                      setAdding(false);
                      setNewText("");
                      setNewTopics("");
                    }}
                    className="px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:bg-accent transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={onAdd}
                    disabled={!newText.trim() || busy === "add"}
                    className="px-3 py-1.5 rounded-lg bg-brand text-brand-foreground text-sm font-medium hover:bg-brand-hover disabled:opacity-50 transition-colors"
                  >
                    {busy === "add" ? "Saving…" : "Save"}
                  </button>
                </div>
              </div>
            )}

            {memories === null ? (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                <div className="w-4 h-4 border-2 border-border border-t-foreground/60 rounded-full animate-spin" />
                Loading memories…
              </div>
            ) : count === 0 && !adding ? (
              <div className="py-10 text-center">
                <p className="text-sm text-foreground">No memories yet.</p>
                <p className="text-xs text-muted-foreground mt-1">
                  The assistant saves useful details from your chats here, like your role, projects and preferences.
                </p>
              </div>
            ) : visible.length === 0 && count > 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">No memories match “{query}”.</p>
            ) : (
              <div className="rounded-xl border border-border divide-y divide-border">
                {visible.map((m) =>
                  editingId === m.id ? (
                    <div key={m.id} className="p-3 space-y-2">
                      <textarea
                        className={`${inputClass} resize-none`}
                        rows={3}
                        autoFocus
                        maxLength={2000}
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                      />
                      <input
                        className={inputClass}
                        placeholder="Topics (comma-separated)"
                        value={editTopics}
                        onChange={(e) => setEditTopics(e.target.value)}
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => setEditingId(null)}
                          className="px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:bg-accent transition-colors"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={() => onSaveEdit(m.id)}
                          disabled={!editText.trim() || busy === m.id}
                          className="px-3 py-1.5 rounded-lg bg-brand text-brand-foreground text-sm font-medium hover:bg-brand-hover disabled:opacity-50 transition-colors"
                        >
                          {busy === m.id ? "Saving…" : "Save"}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div key={m.id} className="group p-3 flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-foreground leading-relaxed break-words">{m.memory}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          {m.topics.map((t) => (
                            <span key={t} className="px-1.5 py-0.5 rounded-md bg-secondary text-[11px] text-muted-foreground">
                              {t}
                            </span>
                          ))}
                          <span className="text-[11px] text-muted-foreground">{formatDate(m.updated_at)}</span>
                        </div>
                      </div>
                      {confirmDeleteId === m.id ? (
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                          <span className="text-xs text-muted-foreground">Delete?</span>
                          <button
                            onClick={() => onDelete(m.id)}
                            disabled={busy === m.id}
                            className="px-2 py-1 rounded-md text-xs font-medium bg-red-600 text-white hover:bg-red-500 disabled:opacity-50"
                          >
                            {busy === m.id ? "…" : "Delete"}
                          </button>
                          <button
                            onClick={() => setConfirmDeleteId(null)}
                            className="px-2 py-1 rounded-md text-xs text-muted-foreground hover:bg-accent"
                          >
                            Keep
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-0.5 flex-shrink-0 opacity-60 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => startEdit(m)}
                            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent"
                            aria-label="Edit memory"
                            title="Edit"
                          >
                            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
                          </button>
                          <button
                            onClick={() => {
                              setConfirmDeleteId(m.id);
                              setEditingId(null);
                            }}
                            className="p-1.5 rounded-md text-muted-foreground hover:text-red-500 hover:bg-red-500/10"
                            aria-label="Delete memory"
                            title="Delete"
                          >
                            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" /></svg>
                          </button>
                        </div>
                      )}
                    </div>
                  )
                )}
              </div>
            )}
          </div>

          {count > 0 && (
            <div className="px-6 py-3 border-t border-border flex items-center justify-between gap-3">
              <p className="text-[11px] text-muted-foreground">
                Keeps up to {limit}; the oldest are replaced as new ones are learned.
              </p>
              {confirmClear ? (
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">Forget all {count}?</span>
                  <button
                    onClick={onClear}
                    disabled={busy === "clear"}
                    className="px-2 py-1 rounded-md text-xs font-medium bg-red-600 text-white hover:bg-red-500 disabled:opacity-50"
                  >
                    {busy === "clear" ? "…" : "Forget all"}
                  </button>
                  <button onClick={() => setConfirmClear(false)} className="px-2 py-1 rounded-md text-xs text-muted-foreground hover:bg-accent">
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmClear(true)}
                  className="text-xs text-red-500 hover:underline whitespace-nowrap"
                >
                  Forget everything
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
