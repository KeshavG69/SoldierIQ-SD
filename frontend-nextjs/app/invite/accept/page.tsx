"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { invitationsApi, ValidateInvitationResponse } from "@/lib/api/invitations";

function AcceptInner() {
  const router = useRouter();
  const params = useSearchParams();
  const inv = params.get("inv") || "";
  const org = params.get("org") || "";

  const [loading, setLoading] = useState(true);
  const [invite, setInvite] = useState<ValidateInvitationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  useEffect(() => {
    if (!inv || !org) {
      setError("This invitation link is invalid.");
      setLoading(false);
      return;
    }
    invitationsApi
      .validate(inv, org)
      .then((data) => {
        setInvite(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(e?.response?.data?.detail || "This invitation is invalid or has expired.");
        setLoading(false);
      });
  }, [inv, org]);

  const handleAccept = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!invite) return;
    setError(null);
    if (!invite.user_exists) {
      if (!firstName.trim() || !lastName.trim()) return setError("Please enter your name.");
      if (password.length < 8) return setError("Password must be at least 8 characters.");
      if (password !== confirm) return setError("Passwords do not match.");
    }
    setSubmitting(true);
    try {
      const res = await invitationsApi.accept({
        invitation_id: inv,
        organization_id: org,
        ...(invite.user_exists ? {} : { firstName, lastName, password }),
      });
      if (res.access_token) {
        localStorage.setItem("access_token", res.access_token);
        if (res.refresh_token) localStorage.setItem("refresh_token", res.refresh_token);
        router.push("/dashboard");
      } else {
        router.push("/auth/login");
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Could not accept the invitation.");
      setSubmitting(false);
    }
  };

  const inputCls =
    "w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15 transition-all";

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="flex items-center gap-2.5 justify-center mb-6">
          <div className="w-8 h-8 rounded-md bg-brand flex items-center justify-center shadow-accent">
            <svg className="w-5 h-5 text-brand-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </div>
          <span className="text-lg font-semibold tracking-tight text-foreground">SoldierIQ</span>
        </div>

        <div className="rounded-2xl border border-border bg-card shadow-lg p-6">
          {loading ? (
            <div className="py-10 flex flex-col items-center gap-3">
              <span className="w-6 h-6 border-2 border-brand/30 border-t-brand rounded-full animate-spin" />
              <span className="text-sm text-muted-foreground">Checking your invitation…</span>
            </div>
          ) : error && !invite ? (
            <div className="text-center py-6">
              <div className="w-11 h-11 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
                <svg className="w-5 h-5 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              </div>
              <h1 className="text-base font-semibold text-foreground mb-1">Invitation unavailable</h1>
              <p className="text-sm text-muted-foreground mb-5">{error}</p>
              <Link href="/auth/login" className="text-sm font-medium text-brand hover:underline">Go to sign in</Link>
            </div>
          ) : invite ? (
            <form onSubmit={handleAccept}>
              <h1 className="text-lg font-semibold text-foreground mb-1">
                Join {invite.organization_name || "the organization"}
              </h1>
              <p className="text-sm text-muted-foreground mb-5">
                You&apos;ve been invited as <span className="font-medium text-foreground capitalize">{invite.role}</span> ·{" "}
                <span className="font-mono text-xs">{invite.email}</span>
              </p>

              {!invite.user_exists && (
                <div className="space-y-3 mb-4">
                  <div className="grid grid-cols-2 gap-3">
                    <input className={inputCls} placeholder="First name" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
                    <input className={inputCls} placeholder="Last name" value={lastName} onChange={(e) => setLastName(e.target.value)} />
                  </div>
                  <input className={inputCls} type="password" placeholder="Create a password" value={password} onChange={(e) => setPassword(e.target.value)} />
                  <input className={inputCls} type="password" placeholder="Confirm password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                </div>
              )}

              {error && <p className="text-xs text-red-500 mb-3">{error}</p>}

              <button
                type="submit"
                disabled={submitting}
                className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-brand text-brand-foreground text-sm font-medium hover:bg-brand-hover shadow-accent disabled:opacity-60 transition-all"
              >
                {submitting ? (
                  <span className="w-4 h-4 border-2 border-current/30 border-t-current rounded-full animate-spin" />
                ) : invite.user_exists ? (
                  "Accept & join"
                ) : (
                  "Create account & join"
                )}
              </button>

              {invite.user_exists && (
                <p className="text-[11px] text-muted-foreground text-center mt-3">
                  You already have an account — after joining, sign in to continue.
                </p>
              )}
            </form>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default function InviteAcceptPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <AcceptInner />
    </Suspense>
  );
}
