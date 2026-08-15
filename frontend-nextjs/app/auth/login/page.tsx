"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/lib/stores/authStore";

export default function LoginPage() {
  const router = useRouter();
  const { login, isLoading, error, clearError } = useAuthStore();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [zulu, setZulu] = useState("------Z");

  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const hh = String(d.getUTCHours()).padStart(2, "0");
      const mm = String(d.getUTCMinutes()).padStart(2, "0");
      const ss = String(d.getUTCSeconds()).padStart(2, "0");
      setZulu(`${hh}${mm}${ss}Z`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearError();
    try {
      await login({ username, password });
      router.push("/dashboard");
    } catch {
      /* handled by store */
    }
  };

  const now = new Date();
  const dtg = `${String(now.getUTCDate()).padStart(2, "0")}${String(now.getUTCHours()).padStart(2, "0")}${String(now.getUTCMinutes()).padStart(2, "0")}Z${now
    .toLocaleString("en-US", { month: "short", timeZone: "UTC" })
    .toUpperCase()}${String(now.getUTCFullYear()).slice(2)}`;

  return (
    <div className="ops min-h-screen flex flex-col">
      {/* Classification strip */}
      <div className="classification">
        <div className="mx-auto max-w-[1280px] w-full px-6 h-7 flex items-center justify-between">
          <span><span className="sig">●</span>&nbsp;&nbsp;UNCLASSIFIED&nbsp;&nbsp;//&nbsp;&nbsp;Access Control</span>
          <span>Form A · Sheet 01</span>
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
          <span className="label">
            DTG <span className="label-ink mono">{dtg}</span>
          </span>
        </div>
      </header>

      {/* Main split */}
      <main className="flex-1 grid grid-cols-1 lg:grid-cols-12">
        {/* Left brief */}
        <aside className="hidden lg:flex col-span-5 flex-col justify-between border-r border-[var(--rule-strong)] p-10 xl:p-14 bg-[var(--bg-alt)] relative">
          <div>
            <div className="label label-od mb-8">§ 001 · Preamble</div>
            <h1
              className="cmd-heavy text-[56px] xl:text-[72px] text-[var(--ink-strong)]"
              style={{ letterSpacing: "-0.025em", lineHeight: "0.96" }}
            >
              Present
              <br />
              your
              <br />
              <span className="text-[var(--od)]">credentials</span>.
            </h1>

            <p className="mt-10 text-[15px] leading-[1.7] text-[var(--ink-muted)] max-w-[40ch]">
              Access is granted by username or recorded email. Sessions are
              logged to the operator ledger for the duration of the connection.
            </p>
          </div>

          {/* Operational readout */}
          <div className="panel p-5">
            <div className="label label-od mb-3">System readout</div>
            <dl className="grid grid-cols-2 gap-y-3 gap-x-6 text-[13px]">
              <div>
                <dt className="label">Host</dt>
                <dd className="mono text-[var(--ink-strong)] mt-0.5">SIQ-01</dd>
              </div>
              <div>
                <dt className="label">Net</dt>
                <dd className="mono text-[var(--ink-strong)] mt-0.5 flex items-center gap-2">
                  <span className="dot dot-ok" /> OPS-3
                </dd>
              </div>
              <div>
                <dt className="label">UTC</dt>
                <dd className="mono text-[var(--ink-strong)] mt-0.5">{zulu}</dd>
              </div>
              <div>
                <dt className="label">Build</dt>
                <dd className="mono text-[var(--ink-strong)] mt-0.5">0.9.4</dd>
              </div>
            </dl>
          </div>
        </aside>

        {/* Right form */}
        <section className="col-span-12 lg:col-span-7 flex flex-col">
          <div className="flex-1 flex items-center justify-center p-6 sm:p-10 lg:p-14">
            <div className="w-full max-w-[460px]">
              <div className="flex items-baseline justify-between mb-2">
                <span className="label label-od">Form A — Sign in</span>
                <span className="label">01 / 02</span>
              </div>
              <div className="hairline-strong mb-10" />

              <form onSubmit={handleSubmit} className="space-y-7">
                <div>
                  <label htmlFor="username" className="label block mb-2">Handle or email</label>
                  <input
                    id="username"
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                    autoFocus
                    autoComplete="username"
                    placeholder="operator@unit.gov"
                    className="field"
                  />
                </div>

                <div>
                  <label htmlFor="password" className="label block mb-2">Passphrase</label>
                  <input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    autoComplete="current-password"
                    placeholder="••••••••"
                    className="field"
                  />
                </div>

                {error && (
                  <div className="border-l-2 border-[var(--signal)] pl-4 py-1 bg-[rgba(200,75,60,0.06)]">
                    <div className="label label-sig mb-1">Access denied</div>
                    <p className="text-[14px] text-[var(--ink)] leading-[1.5]">{error}</p>
                  </div>
                )}

                <div className="pt-3 flex items-center justify-between gap-4">
                  <button type="submit" disabled={isLoading} className="btn">
                    {isLoading ? "Verifying…" : "Authenticate"}
                    {!isLoading && (
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
                        <path d="M1 6h10M7 2l4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" />
                      </svg>
                    )}
                  </button>
                  <Link
                    href="/auth/signup"
                    className="label label-ink hover:text-[var(--od)] transition-colors"
                  >
                    Request access →
                  </Link>
                </div>
              </form>

              <div className="hairline mt-14 mb-3" />
              <div className="flex justify-between items-center">
                <span className="label">Session logged</span>
                <span className="label mono label-ink">{zulu}</span>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
