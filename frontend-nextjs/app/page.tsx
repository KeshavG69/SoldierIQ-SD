"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/lib/stores/authStore";

const modules = [
  {
    code: "M1",
    name: "Query",
    tag: "Interrogation",
    body:
      "Natural-language queries against the full archive. Every answer traces to the source line, page, or timestamp.",
    bullets: ["Grounded answers", "Inline citations", "Multi-doc reasoning"],
  },
  {
    code: "M2",
    name: "Map",
    tag: "Visualisation",
    body:
      "Entity, location, and doctrine graphs generated on demand. Collapses an after-action report into a readable mind-map.",
    bullets: ["Concept graphs", "Doctrine trees", "Exportable"],
  },
  {
    code: "M3",
    name: "Synthesise",
    tag: "Product generation",
    body:
      "Reports, flashcards, and audio overviews produced from documents already in your archive. No second system of record.",
    bullets: ["Situation reports", "Study cards", "Podcast briefs"],
  },
  {
    code: "M4",
    name: "Integrate",
    tag: "Field interop",
    body:
      "TAK feeds, transcribed video, image keyframes. Built to operate where attention is scarce and the next decision is waiting.",
    bullets: ["TAK-ready", "Video + audio", "API"],
  },
];

export default function Home() {
  const router = useRouter();
  // Read user reactively, but do NOT block rendering on the background
  // auth check — marketing content should paint immediately.
  const user = useAuthStore((s) => s.user);
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

  // If the background check later reveals we're logged in, silently redirect.
  // The page is already painted by then; there's no loading gate.
  useEffect(() => {
    if (user) router.push("/dashboard");
  }, [user, router]);

  // DTG (date-time group): 181234ZAPR26
  const now = new Date();
  const dtg = `${String(now.getUTCDate()).padStart(2, "0")}${String(now.getUTCHours()).padStart(2, "0")}${String(now.getUTCMinutes()).padStart(2, "0")}Z${now
    .toLocaleString("en-US", { month: "short", timeZone: "UTC" })
    .toUpperCase()}${String(now.getUTCFullYear()).slice(2)}`;

  return (
    <div className="ops min-h-screen">
      {/* ============================================================
          Classification strip
          ============================================================ */}
      <div className="classification">
        <div className="mx-auto max-w-[1280px] px-6 lg:px-8 h-7 flex items-center justify-between">
          <span>
            <span className="sig">●</span>&nbsp;&nbsp;UNCLASSIFIED&nbsp;&nbsp;//&nbsp;&nbsp;Field-Ready Preview
          </span>
          <span className="hidden sm:inline">
            System: SIQ-01 · Build 0.9.4 · DTG&nbsp;<span className="text-[var(--ink)]">{dtg}</span>
          </span>
          <span className="sm:hidden">{zulu}</span>
        </div>
      </div>

      {/* ============================================================
          Masthead
          ============================================================ */}
      <header className="border-b border-[var(--rule-strong)] bg-[var(--bg)]">
        <div className="mx-auto max-w-[1280px] px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-3">
            <span className="inline-flex items-center justify-center w-8 h-8 border border-[var(--od)]">
              <span className="crosshair" />
            </span>
            <span className="cmd-heavy text-[17px] text-[var(--ink-strong)]">SoldierIQ</span>
            <span className="label">Operational Knowledge System</span>
          </Link>
          <nav className="flex items-center gap-5">
            <Link href="/auth/login" className="label label-ink hover:text-[var(--od)] transition-colors">
              Sign in
            </Link>
            <Link href="/auth/signup" className="btn">
              Request access
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
                <path d="M1 6h10M7 2l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="square" />
              </svg>
            </Link>
          </nav>
        </div>
      </header>

      {/* Status strip — operational context bar */}
      <div className="border-b border-[var(--rule)]">
        <div className="mx-auto max-w-[1280px] px-6 lg:px-8 h-9 flex items-center justify-between text-[11px]">
          <div className="flex items-center gap-5 label">
            <span className="flex items-center gap-2">
              <span className="dot dot-ok dot-live" /> Status&nbsp;<span className="label-ink">Ready</span>
            </span>
            <span className="hairline-v hidden sm:inline-block w-px h-3 bg-[var(--rule-strong)]" />
            <span className="hidden sm:inline">
              Archive&nbsp;<span className="label-ink mono">1,247</span>&nbsp;rec
            </span>
            <span className="hairline-v hidden md:inline-block w-px h-3 bg-[var(--rule-strong)]" />
            <span className="hidden md:inline">
              Deployments&nbsp;<span className="label-ink mono">4</span>
            </span>
            <span className="hairline-v hidden lg:inline-block w-px h-3 bg-[var(--rule-strong)]" />
            <span className="hidden lg:inline">
              Uptime&nbsp;<span className="label-ink mono">99.97%</span>
            </span>
          </div>
          <div className="label flex items-center gap-2">
            <span className="hidden sm:inline">UTC</span>
            <span className="label-ink mono">{zulu}</span>
          </div>
        </div>
      </div>

      {/* ============================================================
          HERO
          ============================================================ */}
      <section className="relative border-b border-[var(--rule-strong)]">
        <div className="mx-auto max-w-[1280px] px-6 lg:px-8 pt-16 lg:pt-24 pb-20 lg:pb-28">
          <div className="grid grid-cols-12 gap-6 lg:gap-10">
            {/* Left: gutter label */}
            <div className="hidden lg:block col-span-1">
              <div className="label rotate-[-90deg] origin-top-left translate-y-24 whitespace-nowrap">
                § 001 — Preamble
              </div>
            </div>

            {/* Center: headline */}
            <div className="col-span-12 lg:col-span-7">
              <div className="rise rise-0 label label-od mb-5">
                Operational Intelligence · For the Field
              </div>
              <h1
                className="rise rise-1 cmd-heavy text-[56px] sm:text-[80px] lg:text-[108px] text-[var(--ink-strong)]"
                style={{ letterSpacing: "-0.025em" }}
              >
                Intelligence
                <br />
                at the speed
                <br />
                of <span className="text-[var(--od)]">decision</span>.
              </h1>

              <div className="rise rise-3 mt-10 max-w-[560px]">
                <p className="text-[16px] leading-[1.65] text-[var(--ink-muted)]">
                  Upload documents, transcripts, field video, and SOPs. SoldierIQ
                  turns them into a searchable operational archive you can
                  interrogate, map, and synthesise — every answer cited to the
                  line that produced it.
                </p>
              </div>

              <div className="rise rise-4 mt-10 flex flex-wrap items-center gap-3">
                <Link href="/auth/signup" className="btn">
                  Request access
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
                    <path d="M1 6h10M7 2l4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" />
                  </svg>
                </Link>
                <Link href="/auth/login" className="btn-ghost">
                  Sign in
                </Link>
              </div>
            </div>

            {/* Right: operational sidecar — live-ish readouts */}
            <aside className="col-span-12 lg:col-span-4 lg:col-start-9 mt-8 lg:mt-0">
              <div className="panel bracket p-5 relative rise rise-5">
                <div className="flex items-center justify-between mb-4 pb-3 border-b border-[var(--rule)]">
                  <span className="label label-od">Operator console · SIQ-01</span>
                  <span className="label">Live</span>
                </div>
                <dl className="grid grid-cols-2 gap-y-4 gap-x-6">
                  <div>
                    <dt className="label">Callsign</dt>
                    <dd className="mono text-[14px] text-[var(--ink-strong)] mt-1">SIQ-01</dd>
                  </div>
                  <div>
                    <dt className="label">Grid ref</dt>
                    <dd className="mono text-[14px] text-[var(--ink-strong)] mt-1">38TLM 1402 9340</dd>
                  </div>
                  <div>
                    <dt className="label">DTG</dt>
                    <dd className="mono text-[13px] text-[var(--ink-strong)] mt-1">{dtg}</dd>
                  </div>
                  <div>
                    <dt className="label">Net</dt>
                    <dd className="mono text-[14px] text-[var(--ink-strong)] mt-1 flex items-center gap-2">
                      <span className="dot dot-ok" /> OPS-3
                    </dd>
                  </div>
                  <div className="col-span-2 border-t border-[var(--rule)] pt-4 mt-1">
                    <dt className="label">Archive</dt>
                    <dd className="flex items-baseline gap-3 mt-1">
                      <span className="cmd text-[28px] text-[var(--ink-strong)]">1,247</span>
                      <span className="label">records · 112 sources</span>
                    </dd>
                  </div>
                </dl>
              </div>

              <div className="mt-3 label flex justify-between">
                <span>Fig. 00</span>
                <span>Readouts, anonymised</span>
              </div>
            </aside>
          </div>
        </div>
      </section>

      {/* ============================================================
          FIG. I — Query trace (operational console specimen)
          ============================================================ */}
      <section className="border-b border-[var(--rule-strong)]">
        <div className="mx-auto max-w-[1280px] px-6 lg:px-8 py-16 lg:py-24">
          <div className="flex items-baseline justify-between mb-6">
            <div className="flex items-center gap-3">
              <span className="crosshair" />
              <span className="label label-od">Fig. I — Query trace, operator console</span>
            </div>
            <span className="label">Sanitised for preview</span>
          </div>

          <div className="panel-raised bracket relative">
            {/* Terminal chrome */}
            <div className="flex items-center justify-between px-4 h-10 border-b border-[var(--rule-strong)] bg-[var(--bg-alt)]">
              <div className="flex items-center gap-4 label">
                <span className="label-od">● SIQ-CLI</span>
                <span>/ archive / op-nightwatch</span>
              </div>
              <div className="flex items-center gap-4 label">
                <span className="flex items-center gap-1.5"><span className="dot dot-ok" /> link-up</span>
                <span>DTG {dtg}</span>
              </div>
            </div>

            <div className="grid grid-cols-12">
              {/* Sources */}
              <div className="col-span-12 md:col-span-4 border-b md:border-b-0 md:border-r border-[var(--rule-strong)] p-6">
                <div className="flex items-baseline justify-between mb-4">
                  <span className="label label-od">Sources</span>
                  <span className="label">4 of 112</span>
                </div>
                <ul className="space-y-3">
                  {[
                    { n: "§1", t: "FM 3-21 — Infantry Manual", k: "DOC" },
                    { n: "§2", t: "Comms SOP 042", k: "DOC" },
                    { n: "§3", t: "After-action, 04 Apr", k: "AAR" },
                    { n: "§4", t: "Radio transcript, Patrol 7", k: "TRN" },
                  ].map((s) => (
                    <li key={s.n} className="flex items-baseline gap-3 text-[14px]">
                      <span className="mono label label-od w-7 flex-shrink-0">{s.n}</span>
                      <span className="flex-1 text-[var(--ink)]">{s.t}</span>
                      <span className="mono label">{s.k}</span>
                    </li>
                  ))}
                </ul>

                <div className="mt-6 pt-5 border-t border-[var(--rule)]">
                  <div className="label mb-2">Filter</div>
                  <div className="space-y-1.5 text-[13px] text-[var(--ink-muted)]">
                    <div className="flex justify-between"><span>Doc</span><span className="mono text-[var(--ink)]">86</span></div>
                    <div className="flex justify-between"><span>Transcript</span><span className="mono text-[var(--ink)]">18</span></div>
                    <div className="flex justify-between"><span>After-action</span><span className="mono text-[var(--ink)]">8</span></div>
                  </div>
                </div>
              </div>

              {/* Query + response */}
              <div className="col-span-12 md:col-span-8 p-6 lg:p-8">
                <div className="label label-od mb-2">Query · 038-A</div>
                <div className="mono text-[15px] text-[var(--ink-strong)] mb-6 leading-[1.45]">
                  &gt; summarise comms protocol across SOPs 040-044 and flag contradictions.
                </div>

                <div className="hairline mb-5" />

                <div className="flex items-baseline justify-between mb-3">
                  <span className="label label-od">Response</span>
                  <span className="label">1.84s · 4 refs</span>
                </div>

                <div className="text-[15px] leading-[1.7] text-[var(--ink)] space-y-3 max-w-[60ch]">
                  <p>
                    Three of five SOPs reference <span className="mono text-[var(--od)]">FM 3-21</span>{" "}
                    as governing authority
                    <sup className="mono text-[var(--signal)] ml-0.5">[1]</sup>.
                    SOP <span className="mono text-[var(--od)]">042</span> diverges on callsign
                    rotation
                    <sup className="mono text-[var(--signal)] ml-0.5">[2]</sup>;
                    the after-action on 04 APR documents resulting confusion during
                    Patrol 7
                    <sup className="mono text-[var(--signal)] ml-0.5">[3]</sup>.
                  </p>
                  <p className="text-[var(--ink-muted)]">
                    Recommended: reconcile §4.2 of SOP 042 with the parent manual
                    before the next rotation window.
                  </p>
                </div>

                <div className="hairline mt-6 mb-3" />
                <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                  <span className="label">Cited</span>
                  <span className="mono text-[13px] text-[var(--ink)]">FM 3-21</span>
                  <span className="mono text-[13px] text-[var(--ink)]">SOP 042</span>
                  <span className="mono text-[13px] text-[var(--ink)]">AAR 04-APR</span>
                  <span className="mono text-[13px] text-[var(--ink)]">TRN P-7</span>
                </div>
              </div>
            </div>

            {/* Terminal footer */}
            <div className="flex items-center justify-between px-4 h-9 border-t border-[var(--rule-strong)] bg-[var(--bg-alt)] label">
              <span>cmd / "/" for quick query</span>
              <span className="label-od">Ready</span>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================
          MODULES — M1-M4 capabilities
          ============================================================ */}
      <section className="border-b border-[var(--rule-strong)]">
        <div className="mx-auto max-w-[1280px] px-6 lg:px-8 py-20 lg:py-24">
          <div className="grid grid-cols-12 gap-6 lg:gap-10 mb-12">
            <div className="col-span-12 lg:col-span-4">
              <div className="label label-od">§ 002 · Capabilities</div>
              <h2 className="cmd-heavy text-[40px] sm:text-[52px] lg:text-[60px] mt-4 text-[var(--ink-strong)]" style={{ letterSpacing: "-0.02em" }}>
                Four modules.
                <br />
                <span className="text-[var(--ink-muted)]">Every mission.</span>
              </h2>
            </div>
            <div className="col-span-12 lg:col-span-5 lg:col-start-7 self-end">
              <p className="text-[15.5px] leading-[1.7] text-[var(--ink-muted)]">
                Purpose-built for operators who work against documents under
                time pressure. No AI cheerleading. No hidden state. Each module
                answers a specific operational question — fast, cited, and
                reproducible.
              </p>
            </div>
          </div>

          <div className="hairline-strong" />

          <ol className="grid grid-cols-1 md:grid-cols-2 border-[var(--rule-strong)]">
            {modules.map((m, i) => (
              <li
                key={m.code}
                className={`relative p-6 lg:p-8 border-[var(--rule-strong)] ${
                  i % 2 === 0 ? "md:border-r" : ""
                } ${i < modules.length - 2 ? "border-b md:border-b" : "md:border-b-0 border-b"} ${
                  i === modules.length - 2 ? "md:border-b-0" : ""
                }`}
              >
                <div className="flex items-baseline justify-between mb-5">
                  <span className="cmd text-[52px] text-[var(--od)]" style={{ letterSpacing: "-0.02em" }}>
                    {m.code}
                  </span>
                  <span className="label">{m.tag}</span>
                </div>

                <h3 className="cmd text-[28px] text-[var(--ink-strong)] mb-3" style={{ letterSpacing: "-0.01em" }}>
                  {m.name}.
                </h3>
                <p className="text-[15px] leading-[1.65] text-[var(--ink-muted)] mb-5 max-w-[46ch]">
                  {m.body}
                </p>

                <ul className="flex flex-wrap gap-1.5">
                  {m.bullets.map((b) => (
                    <li
                      key={b}
                      className="mono text-[11px] text-[var(--ink)] px-2 py-1 border border-[var(--rule-strong)] bg-[var(--bg-alt)]"
                    >
                      {b}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ============================================================
          CTA — deploy
          ============================================================ */}
      <section className="border-b border-[var(--rule-strong)]">
        <div className="mx-auto max-w-[1280px] px-6 lg:px-8 py-20 lg:py-28">
          <div className="grid grid-cols-12 gap-6 lg:gap-10 items-end">
            <div className="col-span-12 lg:col-span-8">
              <div className="label label-od mb-4">§ 003 · Deploy</div>
              <h2 className="cmd-heavy text-[44px] sm:text-[60px] lg:text-[76px] text-[var(--ink-strong)]" style={{ letterSpacing: "-0.025em" }}>
                Bring your archive.
                <br />
                <span className="text-[var(--od)]">Begin operations.</span>
              </h2>
            </div>
            <div className="col-span-12 lg:col-span-4 flex flex-wrap lg:justify-end gap-3">
              <Link href="/auth/signup" className="btn">
                Request access
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
                  <path d="M1 6h10M7 2l4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" />
                </svg>
              </Link>
              <Link href="/auth/login" className="btn-ghost">
                Sign in
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================
          Footer
          ============================================================ */}
      <footer>
        <div className="mx-auto max-w-[1280px] px-6 lg:px-8 py-10">
          <div className="grid grid-cols-12 gap-6 lg:gap-10">
            <div className="col-span-12 lg:col-span-4">
              <div className="flex items-center gap-3 mb-3">
                <span className="inline-flex items-center justify-center w-7 h-7 border border-[var(--od)]">
                  <span className="crosshair" />
                </span>
                <span className="cmd-heavy text-[15px] text-[var(--ink-strong)]">SoldierIQ</span>
              </div>
              <p className="text-[13px] leading-[1.7] text-[var(--ink-muted)] max-w-[42ch]">
                Operational knowledge system for field-intelligence teams.
                Built by a small team out of respect for the time of its
                operators.
              </p>
            </div>

            <div className="col-span-6 lg:col-span-2">
              <div className="label mb-3">Access</div>
              <ul className="space-y-2 text-[13.5px]">
                <li><Link href="/auth/login" className="text-[var(--ink)] hover:text-[var(--od)] transition-colors">Sign in</Link></li>
                <li><Link href="/auth/signup" className="text-[var(--ink)] hover:text-[var(--od)] transition-colors">Request access</Link></li>
              </ul>
            </div>

            <div className="col-span-6 lg:col-span-2">
              <div className="label mb-3">System</div>
              <ul className="space-y-2 text-[13px] text-[var(--ink-muted)] mono">
                <li>SIQ-01 · v0.9.4</li>
                <li>Build d82af1c</li>
                <li className="flex items-center gap-2"><span className="dot dot-ok" /> all systems</li>
              </ul>
            </div>

            <div className="col-span-12 lg:col-span-4">
              <div className="label mb-3">Handling</div>
              <p className="text-[12.5px] leading-[1.65] text-[var(--ink-muted)]">
                This system carries no classified information during preview.
                Production deployments honour your organisation's handling
                caveats and chain of custody requirements.
              </p>
            </div>
          </div>

          <div className="hairline mt-10 mb-4" />
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
            <span className="label">© MMXXVI · SoldierIQ · All rights reserved</span>
            <span className="label">UNCLASSIFIED <span className="text-[var(--signal)]">//</span> Field-Ready Preview</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
