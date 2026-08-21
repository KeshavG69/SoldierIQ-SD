"use client";

import { useState } from "react";
import Link from "next/link";
import { accessRequestsApi } from "@/lib/api/accessRequests";

export default function RequestAccessPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await accessRequestsApi.submit({
        requester_email: email.trim(),
        admin_email: adminEmail.trim(),
        requester_name: name.trim() || undefined,
        message: message.trim() || undefined,
      });
      setDone(true);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not submit your request. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="ops min-h-screen flex flex-col">
      {/* Classification strip */}
      <div className="classification">
        <div className="mx-auto max-w-[1280px] w-full px-6 h-7 flex items-center justify-between">
          <span><span className="sig">●</span>&nbsp;&nbsp;UNCLASSIFIED&nbsp;&nbsp;//&nbsp;&nbsp;Access Control</span>
          <span>Form C · Sheet 01</span>
        </div>
      </div>

      {/* Masthead */}
      <header className="border-b border-[var(--rule-strong)]">
        <div className="mx-auto max-w-[1280px] w-full px-6 h-14 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-3">
            <span className="inline-flex items-center justify-center w-7 h-7 border border-[var(--od)]">
              <span className="crosshair" />
            </span>
            <span className="cmd-heavy text-[15px] text-[var(--ink-strong)]">SoldierIQ</span>
            <span className="label hidden sm:inline">Operational Knowledge System</span>
          </Link>
          <Link href="/auth/login" className="label label-ink hover:text-[var(--od)] transition-colors">
            ← Sign in
          </Link>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-[520px]">
          <div className="flex items-baseline justify-between mb-2">
            <span className="label label-od">Form C — Request System Owner access</span>
          </div>
          <div className="hairline-strong mb-8" />

          {done ? (
            <div className="panel p-6">
              <div className="label label-od mb-2">Request submitted</div>
              <p className="text-[15px] leading-[1.7] text-[var(--ink)]">
                Your request was sent to{" "}
                <span className="mono text-[var(--ink-strong)]">{adminEmail}</span>. Once an admin
                approves it, you’ll receive an email invitation to join as a System Owner.
              </p>
              <div className="mt-6">
                <Link href="/auth/login" className="btn">
                  Back to sign in
                </Link>
              </div>
            </div>
          ) : (
            <>
              <p className="text-[14px] leading-[1.7] text-[var(--ink-muted)] mb-8 max-w-[46ch]">
                Ask an organization admin to grant you System Owner access (upload documents and see
                everything in the org). Enter the admin’s email — they’ll review and approve it.
              </p>

              <form onSubmit={handleSubmit} className="space-y-6">
                <div>
                  <label htmlFor="name" className="label block mb-2">Your name</label>
                  <input
                    id="name"
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Jane Operator"
                    className="field"
                  />
                </div>

                <div>
                  <label htmlFor="email" className="label block mb-2">Your email</label>
                  <input
                    id="email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@unit.gov"
                    className="field"
                  />
                </div>

                <div>
                  <label htmlFor="adminEmail" className="label block mb-2">Admin’s email</label>
                  <input
                    id="adminEmail"
                    type="email"
                    required
                    value={adminEmail}
                    onChange={(e) => setAdminEmail(e.target.value)}
                    placeholder="admin@unit.gov"
                    className="field"
                  />
                </div>

                <div>
                  <label htmlFor="message" className="label block mb-2">Note (optional)</label>
                  <textarea
                    id="message"
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    rows={3}
                    placeholder="Why you need access…"
                    className="field resize-none"
                  />
                </div>

                {error && (
                  <div className="border-l-2 border-[var(--signal)] pl-4 py-1 bg-[rgba(200,75,60,0.06)]">
                    <p className="text-[14px] text-[var(--ink)] leading-[1.5]">{error}</p>
                  </div>
                )}

                <div className="pt-2">
                  <button type="submit" disabled={submitting} className="btn">
                    {submitting ? "Submitting…" : "Submit request"}
                  </button>
                </div>
              </form>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
