"use client";

import { useEffect, useState, useCallback } from "react";
import { useAuthStore } from "@/lib/stores/authStore";
import { organizationsApi, OrgMember } from "@/lib/api/organizations";
import { invitationsApi, OrgInvitation } from "@/lib/api/invitations";
import { accessRequestsApi, AccessRequest } from "@/lib/api/accessRequests";
import { Z_INDEX } from "@/lib/constants/zIndex";

const inputCls =
  "px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15 transition-all";

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  system_owner: "System Owner",
  user: "User",
};

function RoleBadge({ role }: { role: string }) {
  const cls =
    role === "admin"
      ? "bg-brand/15 text-brand"
      : role === "system_owner"
        ? "bg-blue-500/15 text-blue-500"
        : "bg-secondary text-muted-foreground";
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {ROLE_LABEL[role] || role}
    </span>
  );
}

export default function TeamModal({ onClose }: { onClose: () => void }) {
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.role === "admin";
  const isSystemOwner = user?.role === "system_owner";
  // Admin invites anyone; System Owner may only invite plain Users.
  const canInvite = isAdmin || isSystemOwner;
  const invitableRoles: Array<"admin" | "system_owner" | "user"> = isAdmin
    ? ["user", "system_owner", "admin"]
    : ["user"];

  const [members, setMembers] = useState<OrgMember[]>([]);
  const [invites, setInvites] = useState<OrgInvitation[]>([]);
  const [accessReqs, setAccessReqs] = useState<AccessRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "system_owner" | "user">("user");
  const [sending, setSending] = useState(false);
  const [lastLink, setLastLink] = useState<string | null>(null);
  const [lastEmailed, setLastEmailed] = useState(false);
  const [lastEmail, setLastEmail] = useState("");
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setMembers(await organizationsApi.listMembers());
      if (isAdmin) {
        try {
          setInvites(await invitationsApi.list());
        } catch {
          /* ignore */
        }
        try {
          setAccessReqs(await accessRequestsApi.list());
        } catch {
          /* ignore */
        }
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to load team.");
    } finally {
      setLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    load();
  }, [load]);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    const email = inviteEmail.trim();
    if (!email) return;
    setSending(true);
    setError(null);
    setLastLink(null);
    try {
      const res = await invitationsApi.send(email, inviteRole);
      setLastLink(res.accept_url);
      setLastEmailed(!!res.emailed);
      setLastEmail(email);
      setInviteEmail("");
      try {
        setInvites(await invitationsApi.list());
      } catch {
        /* ignore */
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to send invitation.");
    } finally {
      setSending(false);
    }
  };

  const handleRemove = async (m: OrgMember) => {
    if (!confirm(`Remove ${m.email || m.username} from this organization?`)) return;
    setBusy(m.user_id);
    try {
      await organizationsApi.removeMember(m.user_id);
      setMembers((x) => x.filter((y) => y.user_id !== m.user_id));
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to remove member.");
    } finally {
      setBusy(null);
    }
  };

  const handleRole = async (m: OrgMember, role: "admin" | "system_owner" | "user") => {
    setBusy(m.user_id);
    try {
      await organizationsApi.changeMemberRole(m.user_id, role);
      setMembers((x) => x.map((y) => (y.user_id === m.user_id ? { ...y, role } : y)));
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to change role.");
    } finally {
      setBusy(null);
    }
  };

  const handleRevoke = async (id: string) => {
    setBusy(id);
    try {
      await invitationsApi.revoke(id);
      setInvites((x) => x.filter((i) => i.id !== id));
    } catch {
      /* ignore */
    } finally {
      setBusy(null);
    }
  };

  const handleApproveRequest = async (req: AccessRequest) => {
    setBusy(req.id);
    setError(null);
    try {
      await accessRequestsApi.approve(req.id);
      // Approved for THIS org → drops out of this org's pending list.
      setAccessReqs((x) => x.filter((r) => r.id !== req.id));
      // Refresh members (an existing user may have just been upgraded to
      // System Owner) and invitations (a new person got a fresh invite).
      try {
        setMembers(await organizationsApi.listMembers());
      } catch {
        /* ignore */
      }
      try {
        setInvites(await invitationsApi.list());
      } catch {
        /* ignore */
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to approve request.");
    } finally {
      setBusy(null);
    }
  };

  const handleDenyRequest = async (req: AccessRequest) => {
    setBusy(req.id);
    try {
      await accessRequestsApi.deny(req.id);
      setAccessReqs((x) => x.filter((r) => r.id !== req.id));
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to deny request.");
    } finally {
      setBusy(null);
    }
  };

  const displayName = (m: OrgMember) =>
    [m.firstName, m.lastName].filter(Boolean).join(" ") || m.username || m.email || "Member";

  return (
    <>
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" style={{ zIndex: Z_INDEX.MODAL }} onClick={onClose} />
      <div
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-2xl px-4"
        style={{ zIndex: Z_INDEX.MODAL + 1 }}
      >
        <div className="rounded-2xl bg-card border border-border shadow-2xl overflow-hidden max-h-[85vh] flex flex-col">
          <div className="px-6 py-4 border-b border-border flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-foreground">Team</h2>
              <p className="text-xs text-muted-foreground mt-0.5">{user?.organization_name}</p>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-md text-muted-foreground hover:bg-accent transition-colors" aria-label="Close">
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </div>

          <div className="overflow-y-auto p-6 space-y-6">
            {error && <p className="text-xs text-red-500">{error}</p>}

            {/* Invite (Admin or System Owner; System Owner may only invite Users) */}
            {canInvite && (
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Invite a teammate</h3>
                <form onSubmit={handleInvite} className="flex gap-2">
                  <input
                    className={`flex-1 ${inputCls}`}
                    type="email"
                    placeholder="colleague@example.com"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                  />
                  <select
                    className={inputCls}
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value as "admin" | "system_owner" | "user")}
                  >
                    {invitableRoles.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABEL[r]}
                      </option>
                    ))}
                  </select>
                  <button
                    type="submit"
                    disabled={sending}
                    className="px-4 rounded-lg bg-brand text-brand-foreground text-sm font-medium hover:bg-brand-hover shadow-accent disabled:opacity-60 transition-all"
                  >
                    {sending ? "…" : "Invite"}
                  </button>
                </form>
                {lastLink && (
                  <div className="mt-2 space-y-1.5">
                    {lastEmailed && (
                      <div className="flex items-center gap-1.5 text-[11px] font-medium text-brand">
                        <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                          <path fillRule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-8 8a1 1 0 01-1.4 0l-4-4a1 1 0 011.4-1.4L8 12.6l7.3-7.3a1 1 0 011.4 0z" clipRule="evenodd" />
                        </svg>
                        Invitation emailed to {lastEmail}
                      </div>
                    )}
                    <div className="flex items-center gap-2 rounded-lg border border-brand/30 bg-brand/[0.06] px-3 py-2">
                      <span className="text-[11px] text-muted-foreground flex-shrink-0">
                        {lastEmailed ? "or copy link:" : "Invite link:"}
                      </span>
                      <span className="text-[11px] font-mono text-foreground truncate flex-1">{lastLink}</span>
                      <button
                        onClick={() => {
                          navigator.clipboard?.writeText(lastLink);
                          setCopied(true);
                          setTimeout(() => setCopied(false), 1500);
                        }}
                        className="text-[11px] font-medium text-brand hover:underline flex-shrink-0"
                      >
                        {copied ? "Copied" : "Copy"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Members */}
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                Members {members.length > 0 && `(${members.length})`}
              </h3>
              {loading ? (
                <div className="py-6 flex justify-center">
                  <span className="w-5 h-5 border-2 border-brand/30 border-t-brand rounded-full animate-spin" />
                </div>
              ) : (
                <div className="space-y-1">
                  {members.map((m) => (
                    <div key={m.user_id} className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-accent/50">
                      <span className="w-8 h-8 rounded-full bg-brand/15 text-brand text-xs font-bold flex items-center justify-center flex-shrink-0">
                        {displayName(m).charAt(0).toUpperCase()}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-foreground truncate">
                          {displayName(m)} {m.is_self && <span className="text-[11px] text-muted-foreground">(you)</span>}
                        </div>
                        <div className="text-[11px] text-muted-foreground truncate">{m.email}</div>
                      </div>
                      <RoleBadge role={m.role} />
                      {isAdmin && !m.is_self && (
                        <div className="flex items-center gap-1">
                          <select
                            value={m.role}
                            disabled={busy === m.user_id}
                            onChange={(e) => handleRole(m, e.target.value as "admin" | "system_owner" | "user")}
                            className="text-[11px] font-medium bg-transparent border border-border rounded px-1.5 py-1 text-muted-foreground hover:text-foreground focus:outline-none focus:border-brand/60 transition-colors disabled:opacity-60"
                          >
                            <option value="user">User</option>
                            <option value="system_owner">System Owner</option>
                            <option value="admin">Admin</option>
                          </select>
                          <button
                            onClick={() => handleRemove(m)}
                            disabled={busy === m.user_id}
                            className="text-[11px] font-medium text-red-500 hover:text-red-600 px-1.5 py-1 rounded transition-colors"
                          >
                            Remove
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Access requests (admin only) — people asking for System Owner
                access in THIS org. Approving sends them an invite for this org;
                the same request must be approved separately in each org. */}
            {isAdmin && accessReqs.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                  Access requests ({accessReqs.length})
                </h3>
                <p className="text-[11px] text-muted-foreground mb-2">
                  Requests for System Owner access to <span className="font-medium">{user?.organization_name}</span>.
                </p>
                <div className="space-y-1">
                  {accessReqs.map((r) => (
                    <div key={r.id} className="flex items-center gap-3 px-2 py-2 rounded-lg bg-surface-2 dark:bg-card/60">
                      <span className="w-8 h-8 rounded-full bg-blue-500/15 text-blue-500 text-xs font-bold flex items-center justify-center flex-shrink-0">
                        {(r.requester_name || r.requester_email).charAt(0).toUpperCase()}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-foreground truncate">
                          {r.requester_name || r.requester_email}
                        </div>
                        <div className="text-[11px] text-muted-foreground truncate">{r.requester_email}</div>
                        {r.message && (
                          <div className="text-[11px] text-muted-foreground mt-0.5 italic truncate">“{r.message}”</div>
                        )}
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        <button
                          onClick={() => handleApproveRequest(r)}
                          disabled={busy === r.id}
                          className="text-[11px] font-medium px-2 py-1 rounded-md bg-brand text-brand-foreground hover:bg-brand-hover shadow-accent disabled:opacity-60 transition-all"
                        >
                          {busy === r.id ? "…" : "Approve"}
                        </button>
                        <button
                          onClick={() => handleDenyRequest(r)}
                          disabled={busy === r.id}
                          className="text-[11px] font-medium text-red-500 hover:text-red-600 px-1.5 py-1 rounded transition-colors"
                        >
                          Deny
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Pending invitations (admin only) */}
            {isAdmin && invites.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Pending invitations</h3>
                <div className="space-y-1">
                  {invites.map((i) => (
                    <div key={i.id} className="flex items-center gap-3 px-2 py-2 rounded-lg">
                      <span className="w-8 h-8 rounded-full bg-surface-2 border border-dashed border-border text-muted-foreground text-xs flex items-center justify-center flex-shrink-0">
                        @
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-foreground truncate">{i.email}</div>
                        <div className="text-[11px] text-muted-foreground">Invited as {i.role}</div>
                      </div>
                      <button
                        onClick={() => handleRevoke(i.id)}
                        disabled={busy === i.id}
                        className="text-[11px] font-medium text-red-500 hover:text-red-600 px-1.5 py-1 rounded transition-colors"
                      >
                        Revoke
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
